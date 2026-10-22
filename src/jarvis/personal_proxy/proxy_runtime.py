"""The running proxy as the application sees it: the service, the handlers that
feed it, and the resources it owns, started and stopped in a fixed order.

Start: the service, then the bus subscriptions, so nothing reaches a service
that is not running. Hiding the window declines a pending question: nothing the
user can no longer see may be confirmed on their behalf.
Stop: unsubscribe first, then interrupt and close the service (which gives the
microphone back and stops the speaker), then close the second HTTP client.
Stopping twice is harmless."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from jarvis.audio.input import UtteranceChunk
from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import TextSubmissionResult
from jarvis.personal_proxy.proxy_submissions import ProxySubmissions
from jarvis.ui.contract import VisibilityMode
from jarvis.ui.visibility import VisibilityModeChanged

Subscription = tuple[type, Callable]


class RunnableService(Protocol):
    def start(self) -> None: ...

    def interrupt(self) -> None: ...

    def cancel_pending_question(self) -> None: ...

    async def close(self) -> None: ...


class PersonalProxyRuntime:
    def __init__(
        self,
        *,
        service: RunnableService,
        submissions: ProxySubmissions,
        bus: EventBus,
        client: httpx.AsyncClient,
    ) -> None:
        self._service = service
        self._submissions = submissions
        self._bus = bus
        self._client = client
        self._subscriptions: list[Subscription] = []
        self._stopped = False

    def __repr__(self) -> str:
        return f"PersonalProxyRuntime(stopped={self._stopped})"

    def start(self) -> None:
        if self._stopped or self._subscriptions:
            return
        self._service.start()
        self._subscriptions = [
            (UtteranceChunk, self._submissions.on_utterance),
            (VisibilityModeChanged, self._on_visibility_changed),
        ]
        for event_type, handler in self._subscriptions:
            self._bus.subscribe(event_type, handler)

    async def submit_text(self, text: str) -> TextSubmissionResult:
        return await self._submissions.submit_text(text)

    def interrupt(self) -> None:
        self._service.interrupt()

    async def _on_visibility_changed(self, event: VisibilityModeChanged) -> None:
        if event.mode is VisibilityMode.HIDDEN:
            self._service.cancel_pending_question()

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        for event_type, handler in self._subscriptions:
            self._bus.unsubscribe(event_type, handler)
        self._subscriptions = []
        try:
            self._service.interrupt()
            await self._service.close()
        finally:
            await self._client.aclose()
