#!/usr/bin/env python3
"""Manual spike for bilingual Russian/English TTS routing.

This is a human-run check. It compares three routing variants over the same
charset-segmented bilingual text:
- ru, en -> Silero;
- ru -> Silero, en -> Piper;
- ru, en -> Piper.

The script loads only the engines required by the selected route, synthesizes
segments concurrently, and submits playback through OrderedPlayback so audible
output stays in text order even when one engine finishes earlier.

Usage examples:
  python -m manual.manual_check_bilingual_tts_routes
    --piper-ru-model D:\\voices\\ru.onnx
  python -m manual.manual_check_bilingual_tts_routes --route silero_ru_piper_en
  python -m manual.manual_check_bilingual_tts_routes
    --route piper_ru_en --piper-ru-model D:\\voices\\ru.onnx
"""

from __future__ import annotations

import argparse
import asyncio
import io
import time
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import sounddevice as sd
import soundfile as sf

from jarvis.audio.language_segments import segment_by_charset
from jarvis.audio.tts import OrderedPlayback
from jarvis.audio.tts_silero import normalize_numbers, transliterate_latin
from jarvis.audio.utils import samples_to_wav_bytes
from jarvis.core.config import TtsSettings

SILERO = "silero"
PIPER = "piper"
DEFAULT_PIPER_EN_MODEL = Path(
    ".local-models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
)
DEFAULT_ROUTE = "all"


@dataclass(frozen=True)
class RouteSpec:
    label: str
    ru_engine: str
    en_engine: str


@dataclass(frozen=True)
class SampleText:
    label: str
    text: str


@dataclass(frozen=True)
class SegmentPlan:
    index: int
    language: str
    engine_label: str
    text: str


@dataclass(frozen=True)
class SegmentMeasurement:
    index: int
    language: str
    engine_label: str
    synth_seconds: float
    text: str


class SpeechEngine(Protocol):
    async def warm_up(self) -> None: ...

    async def synthesize(self, text: str) -> bytes: ...


ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec("silero_ru_en", ru_engine=SILERO, en_engine=SILERO),
    RouteSpec("silero_ru_piper_en", ru_engine=SILERO, en_engine=PIPER),
    RouteSpec("piper_ru_en", ru_engine=PIPER, en_engine=PIPER),
)

SAMPLES: tuple[SampleText, ...] = (
    SampleText(
        "code_switch_short",
        "Проверь parser и верни JSON без markdown.",
    ),
    SampleText(
        "technical_terms",
        "Для APIClient важны latency, retry policy и корректный failure mode.",
    ),
    SampleText(
        "sentence_mix",
        "Сначала объясни по-русски. Then give me a short English summary.",
    ),
)


class SileroRouteEngine:
    def __init__(
        self, language: str, package: str, voice: str, sample_rate: int
    ) -> None:
        self._language = language
        self._package = package
        self._voice = voice
        self._sample_rate = sample_rate
        self._model = None

    async def warm_up(self) -> None:
        await self._ensure_model()

    async def synthesize(self, text: str) -> bytes:
        model = await self._ensure_model()
        cleaned = _clean_text_for_silero(text, self._language)
        audio_tensor = await asyncio.to_thread(
            model.apply_tts,
            text=cleaned,
            speaker=self._voice,
            sample_rate=self._sample_rate,
        )
        return samples_to_wav_bytes(audio_tensor, self._sample_rate)

    async def _ensure_model(self):
        if self._model is None:
            import silero

            self._model = (
                await asyncio.to_thread(
                    silero.silero_tts,
                    language=self._language,
                    speaker=self._package,
                )
            )[0]
        return self._model


class PiperRouteEngine:
    def __init__(
        self, model_path: Path, config_path: Path | None, use_cuda: bool
    ) -> None:
        self._model_path = model_path
        self._config_path = config_path
        self._use_cuda = use_cuda
        self._voice = None

    async def warm_up(self) -> None:
        await self._ensure_voice()

    async def synthesize(self, text: str) -> bytes:
        voice = await self._ensure_voice()
        return await asyncio.to_thread(
            _piper_chunks_to_wav_bytes, voice.synthesize(text)
        )

    async def _ensure_voice(self):
        if self._voice is None:
            from piper.voice import PiperVoice

            self._voice = await asyncio.to_thread(
                PiperVoice.load,
                model_path=str(self._model_path),
                config_path=str(self._config_path)
                if self._config_path is not None
                else None,
                use_cuda=self._use_cuda,
            )
        return self._voice


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--route",
        choices=(DEFAULT_ROUTE, *route_labels()),
        default=DEFAULT_ROUTE,
        help="Route to test. Defaults to all routes.",
    )
    parser.add_argument(
        "--sample",
        choices=(DEFAULT_ROUTE, *sample_labels()),
        default=DEFAULT_ROUTE,
        help="Sample text to test. Defaults to all samples.",
    )
    parser.add_argument("--silero-ru-package", default="v3_1_ru")
    parser.add_argument(
        "--silero-ru-voice",
        default=TtsSettings().languages["ru"].speaker,
    )
    parser.add_argument("--silero-en-package", default="v3_en")
    parser.add_argument("--silero-en-voice", default="en_0")
    parser.add_argument("--silero-sample-rate", type=int, default=48000)
    parser.add_argument(
        "--piper-en-model",
        default=str(DEFAULT_PIPER_EN_MODEL),
        help="English Piper .onnx model path.",
    )
    parser.add_argument("--piper-en-config", help="English Piper .json config path.")
    parser.add_argument(
        "--piper-ru-model",
        help="Russian Piper .onnx model path. Required for piper_ru_en.",
    )
    parser.add_argument("--piper-ru-config", help="Russian Piper .json config path.")
    parser.add_argument(
        "--use-cuda", action="store_true", help="Pass use_cuda=True to Piper."
    )
    return parser


def route_labels() -> tuple[str, ...]:
    return tuple(route.label for route in ROUTES)


def sample_labels() -> tuple[str, ...]:
    return tuple(sample.label for sample in SAMPLES)


def selected_routes(label: str) -> tuple[RouteSpec, ...]:
    if label == DEFAULT_ROUTE:
        return ROUTES
    return tuple(route for route in ROUTES if route.label == label)


def selected_samples(label: str) -> tuple[SampleText, ...]:
    if label == DEFAULT_ROUTE:
        return SAMPLES
    return tuple(sample for sample in SAMPLES if sample.label == label)


def build_segment_plan(route: RouteSpec, text: str) -> tuple[SegmentPlan, ...]:
    plans: list[SegmentPlan] = []
    for index, segment in enumerate(segment_by_charset(text)):
        plans.append(
            SegmentPlan(
                index=index,
                language=segment.language,
                engine_label=engine_for_language(route, segment.language),
                text=segment.text,
            )
        )
    return tuple(plans)


def engine_for_language(route: RouteSpec, language: str) -> str:
    if language == "en":
        return route.en_engine
    return route.ru_engine


def resolve_piper_config(model_path: Path, config_arg: str | None) -> Path | None:
    if config_arg:
        config_path = Path(config_arg)
        if not config_path.exists():
            raise FileNotFoundError(f"Piper config file does not exist: {config_path}")
        return config_path
    derived = Path(f"{model_path}.json")
    if derived.exists():
        return derived
    raise FileNotFoundError(
        f"No Piper config file was supplied and the default {derived} was not found."
    )


def resolve_required_model(path_arg: str | None, language: str) -> Path:
    if not path_arg:
        raise FileNotFoundError(
            f"{language} Piper route requires a --piper-{language}-model path"
        )
    model_path = Path(path_arg)
    if not model_path.exists():
        raise FileNotFoundError(f"Piper model file does not exist: {model_path}")
    return model_path


def validate_piper_models_for_routes(
    routes: tuple[RouteSpec, ...],
    piper_ru_model: str | None,
    piper_en_model: str | None,
) -> None:
    needs_ru = any(route.ru_engine == PIPER for route in routes)
    needs_en = any(route.en_engine == PIPER for route in routes)
    if needs_ru:
        resolve_required_model(piper_ru_model, "ru")
    if needs_en:
        resolve_required_model(piper_en_model, "en")


async def build_engines(
    args: argparse.Namespace, routes: tuple[RouteSpec, ...]
) -> dict[str, SpeechEngine]:
    validate_piper_models_for_routes(routes, args.piper_ru_model, args.piper_en_model)
    engines: dict[str, SpeechEngine] = {}
    if any(route.ru_engine == SILERO for route in routes):
        engines["ru:silero"] = SileroRouteEngine(
            "ru",
            args.silero_ru_package,
            args.silero_ru_voice,
            args.silero_sample_rate,
        )
    if any(route.en_engine == SILERO for route in routes):
        engines["en:silero"] = SileroRouteEngine(
            "en",
            args.silero_en_package,
            args.silero_en_voice,
            args.silero_sample_rate,
        )
    if any(route.ru_engine == PIPER for route in routes):
        model_path = resolve_required_model(args.piper_ru_model, "ru")
        engines["ru:piper"] = PiperRouteEngine(
            model_path,
            resolve_piper_config(model_path, args.piper_ru_config),
            args.use_cuda,
        )
    if any(route.en_engine == PIPER for route in routes):
        model_path = resolve_required_model(args.piper_en_model, "en")
        engines["en:piper"] = PiperRouteEngine(
            model_path,
            resolve_piper_config(model_path, args.piper_en_config),
            args.use_cuda,
        )
    await asyncio.gather(*(engine.warm_up() for engine in engines.values()))
    return engines


async def run_route_sample(
    route: RouteSpec,
    sample: SampleText,
    engines: dict[str, SpeechEngine],
    play: Callable[[bytes], Awaitable[None]],
) -> tuple[SegmentMeasurement, ...]:
    async def play_indexed(index: int, audio: bytes) -> None:
        del index  # OrderedPlayback's player contract carries the unit index
        await play(audio)

    playback = OrderedPlayback(play_indexed)
    plans = build_segment_plan(route, sample.text)
    measurements: list[SegmentMeasurement | None] = [None] * len(plans)

    async def synthesize_and_submit(plan: SegmentPlan) -> None:
        engine = engines[f"{plan.language}:{plan.engine_label}"]
        start = time.perf_counter()
        audio = await engine.synthesize(plan.text)
        measurements[plan.index] = SegmentMeasurement(
            index=plan.index,
            language=plan.language,
            engine_label=plan.engine_label,
            synth_seconds=time.perf_counter() - start,
            text=plan.text,
        )
        await playback.submit(plan.index, audio)

    await asyncio.gather(*(synthesize_and_submit(plan) for plan in plans))
    return tuple(measurement for measurement in measurements if measurement is not None)


async def play_wav_bytes(wav_bytes: bytes) -> None:
    data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    sd.play(data, sample_rate)
    sd.wait()


def print_segment_plan(route: RouteSpec, sample: SampleText) -> None:
    print(f"route,{route.label},sample,{sample.label}")
    for plan in build_segment_plan(route, sample.text):
        print(f"plan,{plan.index},{plan.language},{plan.engine_label},{plan.text}")


async def main() -> None:
    args = build_arg_parser().parse_args()
    routes = selected_routes(args.route)
    samples = selected_samples(args.sample)
    engines = await build_engines(args, routes)

    print("Bilingual TTS routing manual check")
    print("metric,route,sample,total_seconds")
    for route in routes:
        for sample in samples:
            print_segment_plan(route, sample)
            start = time.perf_counter()
            measurements = await run_route_sample(
                route, sample, engines, play_wav_bytes
            )
            total_seconds = time.perf_counter() - start
            print(f"metric,{route.label},{sample.label},{total_seconds:.2f}")
            for item in measurements:
                print(
                    "segment,"
                    f"{route.label},{sample.label},{item.index},{item.language},"
                    f"{item.engine_label},{item.synth_seconds:.2f},{item.text}"
                )


def _clean_text_for_silero(text: str, language: str) -> str:
    normalized = normalize_numbers(text)
    if language == "ru":
        return transliterate_latin(normalized)
    return normalized


def _piper_chunks_to_wav_bytes(chunks) -> bytes:
    chunk_list = list(chunks)
    if not chunk_list:
        raise RuntimeError("Piper returned no audio chunks")

    buffer = io.BytesIO()
    sample_rate: int | None = None
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        for chunk in chunk_list:
            current_sample_rate = int(chunk.sample_rate)
            if sample_rate is None:
                sample_rate = current_sample_rate
                wav_file.setframerate(sample_rate)
            elif current_sample_rate != sample_rate:
                raise RuntimeError(
                    "Piper returned mixed sample rates: "
                    f"{sample_rate} and {current_sample_rate}"
                )
            wav_file.writeframes(chunk.audio_int16_array.tobytes())
    return buffer.getvalue()


if __name__ == "__main__":
    asyncio.run(main())
