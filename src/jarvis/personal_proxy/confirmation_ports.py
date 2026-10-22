"""What the confirmation exchange needs from the outside, as protocols. The real
adapters (chat sink, speaker, microphone gate, transcriber) belong to the service
that composes the stages."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol

from jarvis.personal_proxy.confirmation_blocks import ChatBlock


class SpeechResult(StrEnum):
    SPOKEN = "spoken"
    DISABLED = "disabled"


class ChatSink(Protocol):
    async def post(self, block: ChatBlock) -> None: ...


class ExchangeSpeaker(Protocol):
    async def speak(self, text: str, language: str | None) -> SpeechResult: ...

    def stop(self) -> None: ...


class MicrophoneGate(Protocol):
    async def pause(self) -> None: ...

    async def resume(self) -> None: ...


class AnswerTranscriber(Protocol):
    async def transcribe(self, utterance: bytes) -> str | None:
        """The text of a spoken answer, None when it held no speech."""
        ...


Sleep = Callable[[float], Awaitable[None]]
