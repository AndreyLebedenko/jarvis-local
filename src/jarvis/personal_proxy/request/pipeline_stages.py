"""The stages of the pipeline as injected callables, bound by the application
wiring to their settings and backends. The service imports no backend, engine,
or HTTP client: it only calls these."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass

import numpy as np

from jarvis.personal_proxy.check.check_result import CheckedTranscript
from jarvis.personal_proxy.common.findings import GateResult
from jarvis.personal_proxy.common.payload import OutboundPayload
from jarvis.personal_proxy.gate.gate_context import GateContext
from jarvis.personal_proxy.restoration.restoration_result import RestoredSentence
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeFailure,
    SanitizeResult,
)
from jarvis.personal_proxy.stt.speech_guard import NoSpeech
from jarvis.personal_proxy.stt.stt_result import Transcription


@dataclass(frozen=True)
class PipelineStages:
    transcribe: Callable[[np.ndarray], Awaitable[Transcription | NoSpeech]]
    check: Callable[[Transcription, np.ndarray], Awaitable[CheckedTranscript]]
    sanitize: Callable[[CheckedTranscript], Awaitable[SanitizeResult | SanitizeFailure]]
    gate: Callable[[OutboundPayload, GateContext], GateResult]
    open_stream: Callable[[OutboundPayload], AsyncIterator[str]]
    restore: Callable[
        [AsyncIterator[str], Mapping[str, str]], AsyncIterator[RestoredSentence]
    ]
    warm_up: Callable[[], Awaitable[None]]
    render_spoken: Callable[[str], Awaitable[str]] | None = None
