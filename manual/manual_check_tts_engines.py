#!/usr/bin/env python3
"""Manual handoff for task-2: compare local TTS engines under a live Ollama
cache profile.

Not an automated test. The script is designed for the human to run on the
real machine because it touches live Ollama, GPU memory, and audio playback.
It measures:
- the current Ollama backend contract from config (including flash_attention
  and kv_cache_type);
- the live Ollama response timings for a short warm-up probe;
- first-audio latency for each installed TTS candidate while Gemma stays
  resident in Ollama;
- peak GPU VRAM delta during each candidate run.

The measured runtime path comes from config, not environment variables. To
compare Gemma 64K f16 vs 64K q8_0 cache profiles, run this script twice with
the desired backend config in place and keep the resulting summaries side by
side.

Usage examples:
  python manual/manual_check_tts_engines.py
  python manual/manual_check_tts_engines.py --piper-model D:\\voices\\en_US-lessac-medium.onnx
  python manual/manual_check_tts_engines.py --kokoro-model D:\\models\\kokoro-v1.0.onnx
  python manual/manual_check_tts_engines.py --xtts-model-path D:\\models\\xtts_v2

Expected output fields:
  backend: model, num_ctx, flash_attention, kv_cache_type,
           load_seconds, prompt_eval_seconds, eval_seconds, eval_count
  engine rows: engine, prompt, load_seconds, first_audio_seconds,
               total_seconds, peak_vram_delta_mib
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import sounddevice as sd
import soundfile as sf
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from audio_utils import samples_to_wav_bytes
from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings, Settings, load_settings
from jarvis.dialog.backend import LatencyMetrics, OllamaBackend, ResponseComplete, ResponseToken
from tts import TtsOutput, normalize_numbers, transliterate_latin

BACKEND_PROBE_PROMPT = "Ответь одним коротким предложением: проверка готова?"
TOKEN_DELAY_SECONDS = 0.05
DEFAULT_KOKORO_LANG_CODE = "a"
DEFAULT_KOKORO_VOICE = "af_heart"
DEFAULT_KOKORO_DEVICE = "cuda"
DEFAULT_XTTS_LANGUAGE = "en"
DEFAULT_XTTS_DEVICE = "cuda"
@dataclass(frozen=True)
class PromptSample:
    label: str
    text: str
    language: str

    @property
    def chunks(self) -> tuple[str, ...]:
        return split_text_into_chunks(self.text)


@dataclass(frozen=True)
class BackendProbeResult:
    model: str
    num_ctx: int
    flash_attention: bool | None
    kv_cache_type: str | None
    wall_seconds: float
    load_seconds: float
    prompt_eval_seconds: float
    eval_seconds: float
    eval_count: int


@dataclass(frozen=True)
class PromptMeasurement:
    label: str
    load_seconds: float
    first_audio_seconds: float
    total_seconds: float
    peak_vram_delta_mib: int | None


@dataclass(frozen=True)
class EngineSummary:
    name: str
    details: dict[str, str]
    load_seconds: float
    prompts: list[PromptMeasurement]


@dataclass(frozen=True)
class LoadedEngine:
    name: str
    details: dict[str, str]
    load_seconds: float
    synthesize: Callable[[str, str], Awaitable[bytes]]


class _FixedLanguageEngine:
    """Adapts a LoadedEngine to tts.py's TtsEngine protocol for one probe:
    the probe fixes the language per prompt, so the protocol's per-call
    language hint is deliberately overridden."""

    def __init__(self, loaded: LoadedEngine, language: str) -> None:
        self._loaded = loaded
        self._language = language

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        del language
        return await self._loaded.synthesize(text, self._language)


@dataclass(frozen=True)
class EnginePaths:
    piper_model: Path | None
    piper_config: Path | None
    kokoro_model: Path | None
    xtts_model_path: Path | None
    xtts_config_path: Path | None


PROMPTS = (
    PromptSample("russian", "Скажи коротко: проект готов и все работает.", "ru"),
    PromptSample("english", "Answer in one short sentence: the build is ready.", "en"),
    PromptSample("mixed_latin", "Скажи, как произносятся Gemma4, Jarvis и OpenAI.", "ru"),
    PromptSample("numbers", "Продиктуй числа 3.1415 и 42.", "ru"),
    PromptSample("short_answer", "Ответь очень коротко: да или нет?", "ru"),
    PromptSample("code_like", "Say this code-like phrase: if x == 1: return y.", "en"),
)


def split_text_into_chunks(text: str, chunk_size: int = 3) -> tuple[str, ...]:
    """Deterministic token-ish chunks so the playback latency is repeatable
    enough for a manual comparison."""
    words = text.split()
    if not words:
        return ()
    chunks: list[str] = []
    for start in range(0, len(words), chunk_size):
        chunk = " ".join(words[start : start + chunk_size])
        if start + chunk_size < len(words):
            chunk += " "
        chunks.append(chunk)
    return tuple(chunks)


def _bool_or_none(value: bool | None) -> str:
    if value is None:
        return "unset"
    return "true" if value else "false"


def _format_mib(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _query_gpu_memory_used_mib() -> list[int] | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    values = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            values.append(int(line))
        except ValueError:
            continue
    return values or None


class VramSampler:
    def __init__(self, interval_seconds: float = 0.2) -> None:
        self._interval_seconds = interval_seconds
        self._baseline_mib: int | None = None
        self._peak_delta_mib: int | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def __aenter__(self) -> "VramSampler":
        values = _query_gpu_memory_used_mib()
        if values:
            self._baseline_mib = max(values)
            self._peak_delta_mib = 0
            self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    @property
    def peak_delta_mib(self) -> int | None:
        return self._peak_delta_mib

    async def _run(self) -> None:
        assert self._baseline_mib is not None
        while not self._stop.is_set():
            values = _query_gpu_memory_used_mib()
            if values:
                delta = max(values) - self._baseline_mib
                if self._peak_delta_mib is None or delta > self._peak_delta_mib:
                    self._peak_delta_mib = delta
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except asyncio.TimeoutError:
                continue


class FirstPlayProbe:
    def __init__(self, playback_lock: asyncio.Lock | None = None) -> None:
        self.first_play_at: float | None = None
        self._playback_lock = playback_lock or asyncio.Lock()

    async def play(self, wav_bytes: bytes) -> None:
        if self.first_play_at is None:
            self.first_play_at = time.perf_counter()
        data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        async with self._playback_lock:
            await asyncio.to_thread(sd.play, data, sample_rate)
            await asyncio.to_thread(sd.wait)


def _backend_probe_prompt() -> list[dict[str, str]]:
    return [{"role": "user", "content": BACKEND_PROBE_PROMPT}]


async def run_backend_probe(settings: Settings) -> BackendProbeResult:
    bus = EventBus()
    complete: ResponseComplete | None = None

    async def on_complete(event: ResponseComplete) -> None:
        nonlocal complete
        complete = event

    bus.subscribe(ResponseComplete, on_complete)
    backend = OllamaBackend(bus=bus, settings=settings.backend)

    wall_start = time.perf_counter()
    await backend.chat(messages=_backend_probe_prompt())
    wall_seconds = time.perf_counter() - wall_start

    if complete is None:
        raise RuntimeError("Backend probe finished without ResponseComplete")

    metrics = complete.metrics
    return BackendProbeResult(
        model=settings.backend.model,
        num_ctx=settings.backend.num_ctx,
        flash_attention=settings.backend.flash_attention,
        kv_cache_type=settings.backend.kv_cache_type,
        wall_seconds=wall_seconds,
        load_seconds=metrics.load_seconds,
        prompt_eval_seconds=metrics.prompt_eval_seconds,
        eval_seconds=metrics.eval_seconds,
        eval_count=metrics.eval_count,
    )


def _prepare_wav_bytes(samples: torch.Tensor | list[float] | tuple[float, ...], sample_rate: int) -> bytes:
    tensor = torch.as_tensor(samples, dtype=torch.float32).flatten().cpu()
    return samples_to_wav_bytes(tensor, sample_rate)


async def load_silero_engine(settings: Settings) -> LoadedEngine:
    import silero

    load_started = time.perf_counter()
    model, _ = await asyncio.to_thread(silero.silero_tts, language="ru", speaker="v3_1_ru")
    load_seconds = time.perf_counter() - load_started

    async def synthesize(text: str, language: str) -> bytes:
        del language
        cleaned = transliterate_latin(normalize_numbers(text))
        audio_tensor = await asyncio.to_thread(
            model.apply_tts,
            text=cleaned,
            speaker=settings.tts.voice,
            sample_rate=48000,
        )
        return _prepare_wav_bytes(audio_tensor, 48000)

    return LoadedEngine("silero", {"speaker": settings.tts.voice}, load_seconds, synthesize)


async def load_piper_engine(paths: EnginePaths) -> LoadedEngine:
    if paths.piper_model is None:
        raise FileNotFoundError("Piper model path is not configured")
    from piper.voice import PiperVoice

    config_path = paths.piper_config or Path(f"{paths.piper_model}.json")
    load_started = time.perf_counter()
    voice = await asyncio.to_thread(
        PiperVoice.load,
        str(paths.piper_model),
        config_path=str(config_path),
    )
    load_seconds = time.perf_counter() - load_started

    async def synthesize(text: str, language: str) -> bytes:
        del language
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            await asyncio.to_thread(voice.synthesize, text, wav_file)
        return buffer.getvalue()

    return LoadedEngine(
        "piper",
        {"model": str(paths.piper_model), "config": str(config_path)},
        load_seconds,
        synthesize,
    )


async def load_kokoro_engine(paths: EnginePaths) -> LoadedEngine:
    if paths.kokoro_model is None:
        raise FileNotFoundError("Kokoro model path is not configured")
    from kokoro import KPipeline

    device = DEFAULT_KOKORO_DEVICE if torch.cuda.is_available() else "cpu"
    load_started = time.perf_counter()
    pipeline = await asyncio.to_thread(
        KPipeline,
        model=str(paths.kokoro_model),
        lang_code=DEFAULT_KOKORO_LANG_CODE,
        device=device,
    )
    load_seconds = time.perf_counter() - load_started

    async def synthesize(text: str, language: str) -> bytes:
        del language
        segments = []
        for _gs, _ps, audio in pipeline(
            text,
            voice=DEFAULT_KOKORO_VOICE,
            speed=1.0,
            split_pattern=r"\n+",
        ):
            segments.append(torch.as_tensor(audio, dtype=torch.float32))
        if not segments:
            raise RuntimeError("Kokoro returned no audio")
        return _prepare_wav_bytes(torch.cat([segment.flatten() for segment in segments]), 24000)

    return LoadedEngine(
        "kokoro",
        {
            "model": str(paths.kokoro_model),
            "lang_code": DEFAULT_KOKORO_LANG_CODE,
            "device": device,
        },
        load_seconds,
        synthesize,
    )


async def load_xtts_engine(paths: EnginePaths) -> LoadedEngine:
    if paths.xtts_model_path is None:
        raise FileNotFoundError("XTTS model path is not configured")
    from TTS.api import TTS

    kwargs = {
        "model_path": str(paths.xtts_model_path),
        "progress_bar": False,
    }
    if paths.xtts_config_path is not None:
        kwargs["config_path"] = str(paths.xtts_config_path)
    load_started = time.perf_counter()
    tts = await asyncio.to_thread(TTS, **kwargs)
    load_seconds = time.perf_counter() - load_started
    device = DEFAULT_XTTS_DEVICE if torch.cuda.is_available() else "cpu"
    if hasattr(tts, "to"):
        tts = tts.to(device)
    speakers = list(getattr(tts, "speakers", []) or [])
    speaker = speakers[0] if speakers else "default"
    languages = list(getattr(tts, "languages", []) or [])
    default_language = DEFAULT_XTTS_LANGUAGE if DEFAULT_XTTS_LANGUAGE in languages else (
        languages[0] if languages else DEFAULT_XTTS_LANGUAGE
    )
    sample_rate = int(getattr(getattr(tts, "synthesizer", None), "output_sample_rate", 24000))

    async def synthesize(text: str, language: str) -> bytes:
        chosen_language = language if language in languages else default_language
        wav = await asyncio.to_thread(
            tts.tts,
            text=text,
            speaker=speaker,
            language=chosen_language,
        )
        return _prepare_wav_bytes(wav, sample_rate)

    return LoadedEngine(
        "xtts-v2",
        {
            "model_path": str(paths.xtts_model_path),
            "config_path": str(paths.xtts_config_path) if paths.xtts_config_path else "",
            "device": device,
            "speaker": speaker,
            "language": default_language,
        },
        load_seconds,
        synthesize,
    )


def build_engine_paths(args: argparse.Namespace) -> EnginePaths:
    return EnginePaths(
        piper_model=Path(args.piper_model) if args.piper_model else None,
        piper_config=Path(args.piper_config) if args.piper_config else None,
        kokoro_model=Path(args.kokoro_model) if args.kokoro_model else None,
        xtts_model_path=Path(args.xtts_model_path) if args.xtts_model_path else None,
        xtts_config_path=Path(args.xtts_config_path) if args.xtts_config_path else None,
    )


async def load_available_engines(
    settings: Settings,
    paths: EnginePaths,
) -> list[tuple[str, LoadedEngine]]:
    engines: list[tuple[str, LoadedEngine]] = []
    for name, loader in (
        ("silero", lambda: load_silero_engine(settings)),
        ("piper", lambda: load_piper_engine(paths)),
        ("kokoro", lambda: load_kokoro_engine(paths)),
        ("xtts-v2", lambda: load_xtts_engine(paths)),
    ):
        try:
            engine = await loader()
        except (ImportError, FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
            print(f"[skip] {name}: {exc}")
            continue
        engines.append((name, engine))
    return engines


async def probe_prompt(
    engine: LoadedEngine,
    prompt: PromptSample,
    playback_lock: asyncio.Lock,
    tts_settings,
) -> PromptMeasurement:
    play_probe = FirstPlayProbe(playback_lock=playback_lock)
    tts = TtsOutput(
        settings=tts_settings,
        engine=_FixedLanguageEngine(engine, prompt.language),
        play=play_probe.play,
        playback_lock=playback_lock,
    )
    start = time.perf_counter()
    for chunk in prompt.chunks:
        await tts.on_token(ResponseToken(text=chunk))
        await asyncio.sleep(TOKEN_DELAY_SECONDS)
    await tts.on_response_complete(
        ResponseComplete(metrics=LatencyMetrics(0.0, 0.0, 0.0, 0))
    )
    await tts.wait_for_pending()
    end = time.perf_counter()
    first_audio = play_probe.first_play_at
    return PromptMeasurement(
        label=prompt.label,
        load_seconds=engine.load_seconds,
        first_audio_seconds=0.0 if first_audio is None else first_audio - start,
        total_seconds=end - start,
        peak_vram_delta_mib=None,
    )


async def run_engine_summary(
    engine: LoadedEngine,
    prompts: tuple[PromptSample, ...],
    tts_settings,
) -> EngineSummary:
    playback_lock = asyncio.Lock()
    async with VramSampler() as sampler:
        prompt_rows = []
        for prompt in prompts:
            prompt_rows.append(
                await probe_prompt(engine, prompt, playback_lock, tts_settings)
            )
        if prompt_rows:
            prompt_rows = [
                PromptMeasurement(
                    label=row.label,
                    load_seconds=row.load_seconds,
                    first_audio_seconds=row.first_audio_seconds,
                    total_seconds=row.total_seconds,
                    peak_vram_delta_mib=sampler.peak_delta_mib,
                )
                for row in prompt_rows
            ]
    return EngineSummary(
        name=engine.name,
        details=engine.details,
        load_seconds=engine.load_seconds,
        prompts=prompt_rows,
    )


def print_backend_probe(result: BackendProbeResult) -> None:
    print("\n[backend]")
    print(f"model: {result.model}")
    print(f"num_ctx: {result.num_ctx}")
    print(f"flash_attention: {_bool_or_none(result.flash_attention)}")
    print(f"kv_cache_type: {result.kv_cache_type or 'unset'}")
    print(f"wall_seconds: {result.wall_seconds:.2f}")
    print(f"load_seconds: {result.load_seconds:.2f}")
    print(f"prompt_eval_seconds: {result.prompt_eval_seconds:.2f}")
    print(f"eval_seconds: {result.eval_seconds:.2f}")
    print(f"eval_count: {result.eval_count}")


def print_engine_summary(summary: EngineSummary) -> None:
    print(f"\n[{summary.name}]")
    for key, value in summary.details.items():
        print(f"{key}: {value}")
    print(f"load_seconds: {summary.load_seconds:.2f}")
    print("engine,prompt,load_seconds,first_audio_seconds,total_seconds,peak_vram_delta_mib")
    for row in summary.prompts:
        print(
            f"{summary.name},{row.label},{row.load_seconds:.2f},"
            f"{row.first_audio_seconds:.2f},{row.total_seconds:.2f},"
            f"{_format_mib(row.peak_vram_delta_mib)}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--piper-model")
    parser.add_argument("--piper-config")
    parser.add_argument("--kokoro-model")
    parser.add_argument("--xtts-model-path")
    parser.add_argument("--xtts-config-path")
    return parser


async def main() -> None:
    settings = load_settings()
    args = build_arg_parser().parse_args()
    paths = build_engine_paths(args)

    print("Jarvis TTS engine spike")
    print("Ollama backend config comes from config.toml/config.ui.toml.")
    print(f"backend.model = {settings.backend.model}")
    print(f"backend.num_ctx = {settings.backend.num_ctx}")
    print(f"backend.flash_attention = {_bool_or_none(settings.backend.flash_attention)}")
    print(f"backend.kv_cache_type = {settings.backend.kv_cache_type or 'unset'}")
    print(f"token_delay_seconds = {TOKEN_DELAY_SECONDS}")
    print("Run this script once with kv_cache_type=f16 and once with kv_cache_type=q8_0 to compare the cache profiles.\n")

    backend_result = await run_backend_probe(settings)
    print_backend_probe(backend_result)

    available_engines = await load_available_engines(settings, paths)
    if not available_engines:
        print("\nNo local TTS engines were available.")
        return

    for name, engine in available_engines:
        print(f"\n== {name} ==")
        print(json.dumps(engine.details, ensure_ascii=False, indent=2))
        summary = await run_engine_summary(engine, PROMPTS, settings.tts)
        print_engine_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
