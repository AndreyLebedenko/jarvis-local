"""Binds the stages of the pipeline to their settings and backends, once, so the
service itself imports none of them.

The speech engine and the presence guard are blocking, so they run in a worker
thread; one request is in the speech stage at a time (the service takes one
request at a time and a spoken answer only comes while a request waits)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field

import numpy as np

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.check.check_backend import CheckBackend
from jarvis.personal_proxy.check.check_result import CheckedTranscript
from jarvis.personal_proxy.check.transcript_check import check_transcript
from jarvis.personal_proxy.common.payload import OutboundPayload
from jarvis.personal_proxy.gate.gate import check_outbound_payload
from jarvis.personal_proxy.request.pipeline_stages import PipelineStages
from jarvis.personal_proxy.restoration.restoration import restore_answer
from jarvis.personal_proxy.restoration.restoration_result import RestoredSentence
from jarvis.personal_proxy.sanitize.sanitize import sanitize
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeFailure,
    SanitizeResult,
)
from jarvis.personal_proxy.stt.guarded_transcription import (
    ProbabilitySource,
    transcribe_guarded,
)
from jarvis.personal_proxy.stt.speech_guard import NoSpeech
from jarvis.personal_proxy.stt.stt_engine import SpeechEngine
from jarvis.personal_proxy.stt.stt_result import Transcription


@dataclass(frozen=True)
class StageDependencies:
    settings: PersonalProxySettings
    vad_threshold: float
    engine: SpeechEngine
    probabilities: ProbabilitySource
    backend: CheckBackend
    open_stream: Callable[[OutboundPayload], AsyncIterator[str]]
    topics_text: str = field(repr=False)
    warm_up: Callable[[], Awaitable[None]]


def bind_stages(deps: StageDependencies) -> PipelineStages:
    settings = deps.settings

    async def transcribe(clip: np.ndarray) -> Transcription | NoSpeech:
        return await asyncio.to_thread(
            transcribe_guarded,
            clip,
            deps.engine,
            deps.probabilities,
            vad_threshold=deps.vad_threshold,
            minimum_speech_seconds=settings.stt_min_speech_seconds,
        )

    async def check(
        transcription: Transcription, clip: np.ndarray
    ) -> CheckedTranscript:
        return await check_transcript(transcription, clip, deps.backend, settings)

    async def sanitize_checked(
        checked: CheckedTranscript,
    ) -> SanitizeResult | SanitizeFailure:
        return await sanitize(checked, deps.topics_text, deps.backend, settings)

    def restore(
        deltas: AsyncIterator[str], mapping: Mapping[str, str]
    ) -> AsyncIterator[RestoredSentence]:
        return restore_answer(deltas, mapping, deps.backend, settings)

    return PipelineStages(
        transcribe=transcribe,
        check=check,
        sanitize=sanitize_checked,
        gate=check_outbound_payload,
        open_stream=deps.open_stream,
        restore=restore,
        warm_up=deps.warm_up,
    )
