#!/usr/bin/env python3
"""Manual production check for v1.2.9 bilingual TTS routing (task-4).

This is a human-run check: it plays audio on the real speakers. Unlike
manual_check_bilingual_tts_routes.py (the spike harness with its own
engine classes), this script exercises the actual production wiring:
settings come from load_settings(), the engine comes from
build_tts_engine(), and speech flows through TtsOutput's own token
buffering, charset segmentation, ordered playback, and final tail guard.

Each synthesized unit is reported with the engine that handled it, so
the human can verify the configured route (ru -> silero, en -> piper)
segment by segment while listening for quality and ordering.

Usage:
  python manual/manual_check_bilingual_tts_production.py

Requires [tts.languages.en] to be configured in config.toml (a local
Piper model; Jarvis never downloads models at runtime).
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.audio.language_segments import DEFAULT_LANGUAGE, ENGLISH
from jarvis.audio.tts import TtsEngine, TtsOutput
from jarvis.audio.tts_factory import (
    EngineBuilder,
    build_tts_engine,
    default_engine_builders,
)
from jarvis.core.config import TtsSettings, load_settings
from jarvis.dialog.backend import LatencyMetrics, ResponseComplete, ResponseToken

ReportFn = Callable[[str, str, str], None]

_TOKEN_RE = re.compile(r"\S+\s*")


@dataclass(frozen=True)
class SampleText:
    label: str
    text: str


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
        "Сначала объясни по-русски. Then give me a short English summary. "
        "И в конце добавь вывод одной фразой.",
    ),
)


class ReportingEngine:
    """Wraps a production TtsEngine and reports (engine label, language,
    text) for every synthesis call, without changing the audio path."""

    def __init__(self, label: str, engine: TtsEngine, report: ReportFn) -> None:
        self._label = label
        self._engine = engine
        self._report = report

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        self._report(self._label, language, text)
        return await self._engine.synthesize(text, language)


def reporting_builders(
    settings: TtsSettings,
    report: ReportFn,
    base_builders: dict[str, EngineBuilder] | None = None,
) -> dict[str, EngineBuilder]:
    """The production engine builders, each wrapped so the engines they
    build report every unit they synthesize."""
    base = base_builders if base_builders is not None else default_engine_builders()

    def wrap(label: str, builder: EngineBuilder) -> EngineBuilder:
        def build(route) -> TtsEngine:
            return ReportingEngine(label, builder(route), report)

        return build

    return {label: wrap(label, builder) for label, builder in base.items()}


def stream_tokens(text: str) -> list[str]:
    """Splits sample text into word-sized tokens so the check exercises
    the same incremental feeding path as a live streamed response."""
    return _TOKEN_RE.findall(text)


def _zero_metrics() -> LatencyMetrics:
    return LatencyMetrics(
        load_seconds=0.0, prompt_eval_seconds=0.0, eval_seconds=0.0, eval_count=0
    )


async def run_samples(tts: TtsOutput, samples: tuple[SampleText, ...]) -> None:
    """Feeds each sample through TtsOutput as one streamed response turn,
    waiting for its full playback before starting the next."""
    for sample in samples:
        print(f"sample,{sample.label},{sample.text}")
        for token in stream_tokens(sample.text):
            await tts.on_token(ResponseToken(text=token))
        await tts.on_response_complete(ResponseComplete(metrics=_zero_metrics()))
        await tts.wait_for_pending()


async def main() -> None:
    settings = load_settings()
    routes = settings.tts.languages
    for language, route in sorted(routes.items()):
        print(f"route,{language},{route.engine},{route.model}")

    if ENGLISH not in routes:
        print(
            "error,no [tts.languages.en] route configured - this check needs "
            "the production bilingual route (see config.example.toml)."
        )
        raise SystemExit(1)

    unit_index = 0

    def report(label: str, language: str, text: str) -> None:
        nonlocal unit_index
        print(f"unit,{unit_index},{language},{label},{text}")
        unit_index += 1

    engine = build_tts_engine(settings.tts, reporting_builders(settings.tts, report))
    tts = TtsOutput(settings.tts, engine=engine)

    print("Bilingual TTS production check: listen for correct voices and ordering.")
    await run_samples(tts, SAMPLES)
    print("done,all samples played")


if __name__ == "__main__":
    asyncio.run(main())
