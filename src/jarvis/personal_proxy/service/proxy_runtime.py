"""The running proxy as the application sees it: the service, the handlers that
feed it, and the resources it owns, started and stopped in a fixed order.

Start: the service, then the bus subscriptions, so nothing reaches a service
that is not running. Hiding the window declines a pending question: nothing the
user can no longer see may be confirmed on their behalf.
Stop: unsubscribe first, then interrupt and close the service (which gives the
microphone back and stops the speaker), then run what the chat sink needs once
the service is down (the Journal writer ends the answer it was still holding),
then close the second HTTP client.
Stopping twice is harmless.
A new session starts only while the service is idle: no request in flight and
no question pending, so a send is never cut off."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx

from jarvis.audio.input import UtteranceChunk
from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import (
    NewContextReason,
    NewContextResult,
    TextSubmissionResult,
)
from jarvis.personal_proxy.service.proxy_submissions import ProxySubmissions
from jarvis.ui.contract import VisibilityMode
from jarvis.ui.visibility import VisibilityModeChanged

Subscription = tuple[type, Callable]
NewSessionHook = Callable[[Callable[[], bool]], Awaitable[bool]]


class RunnableService(Protocol):
    @property
    def idle(self) -> bool: ...

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
        on_stopped: Callable[[], Awaitable[None]] | None = None,
        on_new_session: NewSessionHook | None = None,
    ) -> None:
        self._on_stopped = on_stopped
        self._on_new_session = on_new_session
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

    async def start_new_session(self) -> NewContextResult:
        if self._stopped:
            return NewContextResult(NewContextReason.UNAVAILABLE)
        if not self._service.idle:
            return NewContextResult(NewContextReason.BUSY)
        hook = self._on_new_session
        if hook is not None and not await hook(lambda: self._service.idle):
            return NewContextResult(NewContextReason.BUSY)
        return NewContextResult(NewContextReason.ACCEPTED)

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
            await self._finish()

    async def _finish(self) -> None:
        try:
            if self._on_stopped is not None:
                await self._on_stopped()
        finally:
            await self._client.aclose()
