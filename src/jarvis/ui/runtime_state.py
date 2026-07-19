"""Single owner for RuntimeState transitions.

RuntimeStateTracker subscribes to lifecycle bus events and publishes
RuntimeStateChanged. UI wiring renders RuntimeStateChanged only; no other
module decides what the orb state is (story v1.2.14, task 1).

Substatus travels either as a ui_text catalog key (localized by the
renderer, which owns the UI language) or as literal text for values that
are already final, such as an error message.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.core.bus import EventBus
from jarvis.core.lifecycle import (
    TurnAccepted,
    TurnCompleted,
    TurnSource,
    WarmupCompleted,
    WarmupStarted,
)
from jarvis.dialog.backend import ResponseToken
from jarvis.ui.contract import EventLevel, RuntimeState, SystemEvent

logger = logging.getLogger(__name__)

Subscription = tuple[type, Callable]

_TURN_SOURCE_SUBSTATUS_KEY: dict[TurnSource, str] = {
    TurnSource.VOICE: "processing_voice",
    TurnSource.TEXT: "processing_text",
    TurnSource.TEXT_INPUT: "processing_text",
    TurnSource.ATTACHMENT: "processing_attachment",
}


@dataclass(frozen=True)
class RuntimeStateChanged:
    state: RuntimeState
    substatus_key: str | None = None
    substatus_text: str | None = None


class RuntimeStateTracker:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._last: RuntimeStateChanged | None = None

    def subscribe(self) -> list[Subscription]:
        subscriptions: list[Subscription] = [
            (WarmupStarted, self._on_warmup_started),
            (WarmupCompleted, self._on_warmup_completed),
            (TurnAccepted, self._on_turn_accepted),
            (ResponseToken, self._on_response_token),
            (TurnCompleted, self._on_turn_completed),
            (SystemEvent, self._on_system_event),
        ]
        for event_type, handler in subscriptions:
            self._bus.subscribe(event_type, handler)
        return subscriptions

    async def _on_warmup_started(self, event: WarmupStarted) -> None:
        del event
        await self._transition(RuntimeState.WARMING, key="warming_model")

    async def _on_warmup_completed(self, event: WarmupCompleted) -> None:
        # A failed warm-up already surfaces as a WARN system event; the
        # engine keeps accepting input either way, so the orb goes to
        # LISTENING regardless (pre-tracker behavior preserved).
        del event
        await self._transition(RuntimeState.LISTENING, key="ready_to_listen")

    async def _on_turn_accepted(self, event: TurnAccepted) -> None:
        key = _TURN_SOURCE_SUBSTATUS_KEY[event.source]
        await self._transition(RuntimeState.THINKING, key=key)

    async def _on_response_token(self, event: ResponseToken) -> None:
        # SPEAKING only follows an accepted turn. The warm-up request
        # streams ResponseToken through the same bus, and the tracker is
        # subscribed before warm_up() runs - without this guard the orb
        # would announce SPEAKING while the engine is still WARMING.
        del event
        current = self._last.state if self._last is not None else None
        if current not in (RuntimeState.THINKING, RuntimeState.SPEAKING):
            return
        await self._transition(RuntimeState.SPEAKING, key="speaking_response")

    async def _on_turn_completed(self, event: TurnCompleted) -> None:
        del event
        await self._transition(RuntimeState.LISTENING, key="ready_to_listen")

    async def _on_system_event(self, event: SystemEvent) -> None:
        if event.level is EventLevel.ERROR:
            await self._transition(RuntimeState.ERROR, text=event.message)

    async def _transition(
        self, state: RuntimeState, key: str | None = None, text: str | None = None
    ) -> None:
        changed = RuntimeStateChanged(
            state=state, substatus_key=key, substatus_text=text
        )
        if changed == self._last:
            return
        self._last = changed
        await self._bus.publish(RuntimeStateChanged, changed)
