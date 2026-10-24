#!/usr/bin/env python3
"""Human-run check of the transcript check stage (task v2.1.0-4).

Handoff with every step: manual/transcript-check-handoff.md.

  python -m manual.manual_check_transcript_check run --wavs DIR [--extra N]

Runs the recordings in DIR through the guarded speech-to-text stage and then
through the transcript check stage against the live local Ollama endpoint
(`[backend].endpoint`), and prints per recording the engine text, the checked
text, the doubts, `would_ask`, the source, the fallback reason, and the seconds.
The spike v2.1.0-7 cases that exercise the rewrite guard always run first.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Sequence
from pathlib import Path

import httpx
import numpy as np

from jarvis.core.config import load_settings
from jarvis.personal_proxy.check.check_backend import ChatRequest, CheckBackend
from jarvis.personal_proxy.check.check_result import CheckedTranscript, FallbackReason
from jarvis.personal_proxy.check.ollama_check_backend import OllamaCheckBackend
from jarvis.personal_proxy.check.transcript_check import check_transcript
from jarvis.personal_proxy.stt.guarded_transcription import transcribe_guarded
from jarvis.personal_proxy.stt.silero_probabilities import SileroSpeechProbabilities
from jarvis.personal_proxy.stt.speech_guard import NoSpeech
from jarvis.personal_proxy.stt.stt_whisper import FasterWhisperEngine
from manual.manual_check_stt_stage import decode

REWRITE_CASES = ("n_short_translate", "m_trade_house")
DEFAULT_EXTRA = 3
CONNECT_TIMEOUT_SECONDS = 10.0


REJECTED_SAMPLE_REASONS = (
    FallbackReason.INVENTED_ADDRESS,
    FallbackReason.ALPHABET_SWITCH,
)


class RecordingBackend:
    """Remembers the first reply of the last check, the sample the guard saw."""

    def __init__(self, inner: CheckBackend) -> None:
        self._inner = inner
        self.first_reply: str | None = None
        self._calls = 0

    def begin_check(self) -> None:
        self.first_reply = None
        self._calls = 0

    async def complete(self, request: ChatRequest) -> str:
        reply = await self._inner.complete(request)
        if self._calls == 0:
            self.first_reply = reply
        self._calls += 1
        return reply


def ollama_preflight(client: httpx.Client, endpoint: str, model: str) -> str | None:
    """None when the server answers and lists the model, else what to fix."""
    try:
        response = client.get("/api/tags")
        response.raise_for_status()
        names = {entry["name"] for entry in response.json()["models"]}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return (
            f"Ollama does not answer at {endpoint} (GET /api/tags). "
            "Start it, or fix [backend].endpoint; no recording was checked."
        )
    if model not in names and f"{model}:latest" not in names:
        return (
            f"Ollama at {endpoint} does not list the model {model!r} "
            f"(`ollama list`). Run `ollama pull {model}`; no recording was checked."
        )
    return None


def select_recordings(
    available: Sequence[Path], required: Sequence[str], extra: int
) -> list[Path]:
    """The required recordings first, then the first `extra` others, by name."""
    by_name = {path.stem: path for path in available}
    missing = [name for name in required if name not in by_name]
    if missing:
        raise SystemExit(f"missing recordings: {', '.join(missing)}")
    others = [path for path in sorted(available) if path.stem not in required]
    return [by_name[name] for name in required] + others[:extra]


def render_result(result: CheckedTranscript) -> list[str]:
    reason = result.fallback_reason.value if result.fallback_reason else "-"
    lines = [
        f"checked text: {result.text}",
        f"source: {result.source.value}; fallback reason: {reason}",
        f"would_ask: {result.would_ask}; doubts: {len(result.doubts)}",
    ]
    for doubt in result.doubts:
        quoted = f" {doubt.fragment!r}" if doubt.fragment is not None else ""
        lines.append(f"  doubt {doubt.kind.value}{quoted}")
    return lines


async def command_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    proxy = settings.personal_proxy
    available = sorted(args.wavs.glob("*.wav"))
    paths = select_recordings(available, REWRITE_CASES, args.extra)
    print(
        f"[backend].endpoint = {settings.backend.endpoint}; "
        f"check_model = {proxy.check_model}; check_num_ctx = {proxy.check_num_ctx}; "
        f"check_temperature = {proxy.check_temperature}; "
        f"check_top_p = {proxy.check_top_p}; check_top_k = {proxy.check_top_k}; "
        f"check_min_p = {proxy.check_min_p}; "
        f"check_repeat_penalty = {proxy.check_repeat_penalty}; "
        f"doubt_min_listed = {proxy.doubt_min_listed}; "
        f"stt_weak_word_probability = {proxy.stt_weak_word_probability}"
    )
    with httpx.Client(base_url=settings.backend.endpoint, timeout=5.0) as probe:
        problem = ollama_preflight(probe, settings.backend.endpoint, proxy.check_model)
    if problem:
        print(problem)
        return 2
    engine = FasterWhisperEngine(proxy)
    probabilities = SileroSpeechProbabilities()
    timeout = httpx.Timeout(
        CONNECT_TIMEOUT_SECONDS, read=settings.backend.read_timeout_seconds
    )
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = RecordingBackend(OllamaCheckBackend(settings.backend, proxy, client))
        for path in paths:
            await _run_one(path, engine, probabilities, backend, settings)
    return 0


async def _run_one(path, engine, probabilities, backend, settings) -> None:
    proxy = settings.personal_proxy
    clip: np.ndarray = decode(path)
    transcription = transcribe_guarded(
        clip,
        engine,
        probabilities,
        vad_threshold=settings.vad.threshold,
        minimum_speech_seconds=proxy.stt_min_speech_seconds,
    )
    print(f"\n== {path.stem}")
    if isinstance(transcription, NoSpeech):
        print("NO SPEECH; check not run")
        return
    print(f"engine text: {transcription.text}")
    started = time.perf_counter()
    backend.begin_check()
    result = await check_transcript(transcription, clip, backend, proxy)
    elapsed = time.perf_counter() - started
    print("\n".join(render_result(result)))
    if result.fallback_reason in REJECTED_SAMPLE_REASONS:
        print(f"rejected sample: {backend.first_reply}")
    print(f"check seconds: {elapsed:.2f}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--wavs", type=Path, required=True)
    run.add_argument("--extra", type=int, default=DEFAULT_EXTRA)
    run.set_defaults(handler=command_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
