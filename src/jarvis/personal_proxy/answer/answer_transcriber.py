"""The transcriber of a spoken answer to a question: the same guarded speech
stage as the request, over the WAV of the utterance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import numpy as np

from jarvis.personal_proxy.common.visible_text import has_visible_text
from jarvis.personal_proxy.stt.speech_guard import NoSpeech
from jarvis.personal_proxy.stt.stt_result import Transcription
from jarvis.personal_proxy.stt.wav_clip import wav_to_clip

Transcribe = Callable[[np.ndarray], Awaitable[Transcription | NoSpeech]]


class StageAnswerTranscriber:
    def __init__(self, transcribe: Transcribe) -> None:
        self._transcribe = transcribe

    async def transcribe(self, utterance: bytes) -> str | None:
        result = await self._transcribe(wav_to_clip(utterance))
        if isinstance(result, Transcription) and has_visible_text(result.text):
            return result.text
        return None
