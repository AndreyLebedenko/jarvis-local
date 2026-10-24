"""Where speech and typed text enter the proxy: each only enqueues and returns
at once, so the event bus and the transport never wait on the work.

Nothing taken from an utterance or a message is logged or put in an exception;
a dropped item is reported by its kind alone."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from jarvis.audio.input import UtteranceChunk
from jarvis.core.lifecycle import TextSubmissionReason, TextSubmissionResult
from jarvis.personal_proxy.request.proxy_inbox import (
    InboxFullError,
    InboxItem,
    TypedText,
    Utterance,
)
from jarvis.personal_proxy.service.proxy_service import ServiceClosedError

DropReporter = Callable[[], Awaitable[None]]


class Submittable(Protocol):
    def submit(self, item: InboxItem) -> None: ...


class ProxySubmissions:
    def __init__(
        self,
        service: Submittable,
        *,
        text_max_chars: int,
        report_dropped: DropReporter,
    ) -> None:
        self._service = service
        self._text_max_chars = text_max_chars
        self._report_dropped = report_dropped

    async def on_utterance(self, event: UtteranceChunk) -> None:
        try:
            self._service.submit(Utterance(event.wav_bytes))
        except (InboxFullError, ServiceClosedError):
            await self._report_dropped()

    async def submit_text(self, text: str) -> TextSubmissionResult:
        if not text.strip():
            return self._result(TextSubmissionReason.EMPTY)
        if len(text) > self._text_max_chars:
            return self._result(TextSubmissionReason.OVER_LIMIT)
        try:
            self._service.submit(TypedText(text))
        except (InboxFullError, ServiceClosedError):
            return self._result(TextSubmissionReason.BUSY)
        return self._result(TextSubmissionReason.ACCEPTED)

    def _result(self, reason: TextSubmissionReason) -> TextSubmissionResult:
        return TextSubmissionResult(reason, self._text_max_chars)
