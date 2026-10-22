"""What the service needs from the outside, beside the ports of the
confirmation exchange. The real adapters belong to the application wiring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from jarvis.personal_proxy.confirmation_ports import SpeechResult
from jarvis.personal_proxy.service_blocks import ServiceBlock


class ProxyChatSink(Protocol):
    async def post(self, block: ServiceBlock) -> None: ...


class AnswerSpeaker(Protocol):
    """Speaks the answer, one sentence per `speak` call. Each call is parsed on
    its own by the speech layer: a sentence cannot rely on markup opened in an
    earlier call, and the service removes the control tags from every sentence
    before the call."""

    async def speak(self, text: str, language: str | None) -> SpeechResult: ...

    def stop(self) -> None: ...


LanguageProvider = Callable[[], str | None]
