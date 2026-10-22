"""The first stage of a request: turns an inbox item into a checked transcript,
or posts why there is nothing to go on with. Typed text is the user's own words
and skips the speech stage and the check."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from jarvis.personal_proxy.check_result import CheckedTranscript, FallbackReason
from jarvis.personal_proxy.pipeline_stages import PipelineStages
from jarvis.personal_proxy.proxy_inbox import InboxItem, TypedText, Utterance
from jarvis.personal_proxy.service_blocks import NoticeKind
from jarvis.personal_proxy.service_reporter import Reporter
from jarvis.personal_proxy.stt_result import Transcription
from jarvis.personal_proxy.typed_transcript import typed_checked_transcript
from jarvis.personal_proxy.visible_text import has_visible_text
from jarvis.personal_proxy.wav_clip import WavClipError, wav_to_clip


@dataclass(frozen=True)
class Heard:
    checked: CheckedTranscript = field(repr=False)
    whisper_text: str | None = field(repr=False)


class RequestIntake:
    def __init__(self, stages: PipelineStages, reporter: Reporter) -> None:
        self._stages = stages
        self._reporter = reporter

    async def hear(self, item: InboxItem) -> Heard | None:
        if isinstance(item, TypedText):
            heard = Heard(typed_checked_transcript(item.text), None)
        elif isinstance(item, Utterance):
            heard = await self._heard_utterance(item)
        else:
            raise TypeError("the intake takes TypedText or Utterance items")
        if heard is None:
            return None
        if not _has_text_to_send(heard.checked):
            await self._reporter.notice(NoticeKind.NO_SPEECH)
            return None
        return heard

    async def _heard_utterance(self, utterance: Utterance) -> Heard | None:
        clip = await self._clip_of(utterance)
        if clip is None:
            return None
        transcription = await self._stages.transcribe(clip)
        if not isinstance(transcription, Transcription) or not has_visible_text(
            transcription.text
        ):
            await self._reporter.notice(NoticeKind.NO_SPEECH)
            return None
        checked = await self._stages.check(transcription, clip)
        return Heard(checked, transcription.text)

    async def _clip_of(self, utterance: Utterance) -> np.ndarray | None:
        try:
            return wav_to_clip(utterance.wav)
        except WavClipError:
            await self._reporter.notice(NoticeKind.BAD_AUDIO)
            return None


def _has_text_to_send(checked: CheckedTranscript) -> bool:
    if checked.fallback_reason is FallbackReason.EMPTY_TRANSCRIPT:
        return False
    return isinstance(checked.text, str) and has_visible_text(checked.text)
