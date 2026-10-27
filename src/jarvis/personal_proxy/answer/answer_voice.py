"""Speaks text for the service with the microphone paused around it.

A session pauses the microphone before the first sentence it speaks and gives it
back once, when the session ends, whatever ended it. A muted TTS ends the
speech of the session at once; a speaker or microphone failure degrades the
rest of the session to text and is reported as a problem kind, never raised and
never with the cause."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from types import TracebackType

from jarvis.personal_proxy.common.speech_tags import strip_speech_control_tags
from jarvis.personal_proxy.confirmation.confirmation_ports import (
    ExchangeSpeaker,
    MicrophoneGate,
    SpeechResult,
)
from jarvis.personal_proxy.confirmation.resume_completely import resume_completely
from jarvis.personal_proxy.reporting.service_blocks import NoticeKind
from jarvis.personal_proxy.reporting.service_ports import LanguageProvider

RESUME_LIMIT_SECONDS = 10.0


class AnswerVoice:
    def __init__(
        self,
        *,
        speaker: ExchangeSpeaker,
        microphone: MicrophoneGate,
        language: LanguageProvider,
        resume_limit_seconds: float = RESUME_LIMIT_SECONDS,
    ) -> None:
        self._speaker = speaker
        self._microphone = microphone
        self._language = language
        self._resume_limit = resume_limit_seconds

    def session(self) -> SpeechSession:
        return SpeechSession(
            self._speaker, self._microphone, self._language, self._resume_limit
        )

    def stop(self) -> None:
        stop_quietly(self._speaker)


def stop_quietly(speaker: ExchangeSpeaker) -> None:
    with suppress(Exception):
        speaker.stop()


class SpeechSession:
    def __init__(
        self,
        speaker: ExchangeSpeaker,
        microphone: MicrophoneGate,
        language: LanguageProvider,
        resume_limit: float,
    ) -> None:
        self._speaker = speaker
        self._microphone = microphone
        self._language = language
        self._resume_limit = resume_limit
        self._paused = False
        self._muted = False
        self._speech_failed = False
        self._resume_failed = False

    async def __aenter__(self) -> SpeechSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None and issubclass(exc_type, asyncio.CancelledError):
                stop_quietly(self._speaker)
        finally:
            await self._resume()

    def take_problems(self) -> list[NoticeKind]:
        problems = []
        if self._speech_failed:
            problems.append(NoticeKind.SPEECH_FAILED)
        if self._resume_failed:
            problems.append(NoticeKind.MICROPHONE_FAILED)
        self._speech_failed = self._resume_failed = False
        return problems

    async def hold_microphone(self) -> None:
        """Pauses the microphone ahead of the first sentence, for a wait that
        precedes the speech; a failure degrades the session to text."""
        if self._muted:
            return
        try:
            await self._pause_once()
        except Exception:
            self._muted = self._speech_failed = True

    async def say(self, text: str) -> None:
        spoken = strip_speech_control_tags(text)
        if self._muted or not spoken.strip():
            return
        try:
            await self._pause_once()
            result = await self._speaker.speak(spoken, self._language())
        except Exception:
            self._muted = self._speech_failed = True
            return
        if result is SpeechResult.DISABLED:
            self._muted = True
            await self._resume()

    async def _pause_once(self) -> None:
        if self._paused:
            return
        self._paused = True
        await self._microphone.pause()

    async def _resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if not await resume_completely(self._microphone.resume(), self._resume_limit):
            self._resume_failed = True
