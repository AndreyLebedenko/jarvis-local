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
from jarvis.dialog.voice_guide import VoiceGuidePhase, VoiceGuideQueueChanged
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


_EMPTY_QUEUE = VoiceGuideQueueChanged(length=0, in_flight=False)


class RuntimeStateTracker:
    """`ready_state` is the state the orb rests in between turns: LISTENING,
    or MCP_WAITING in MCP mode."""

    def __init__(
        self, bus: EventBus, ready_state: RuntimeState = RuntimeState.LISTENING
    ) -> None:
        self._bus = bus
        self._ready_state = ready_state
        self._last: RuntimeStateChanged | None = None
        self._last_queue = _EMPTY_QUEUE

    def subscribe(self) -> list[Subscription]:
        subscriptions: list[Subscription] = [
            (WarmupStarted, self._on_warmup_started),
            (WarmupCompleted, self._on_warmup_completed),
            (TurnAccepted, self._on_turn_accepted),
            (ResponseToken, self._on_response_token),
            (TurnCompleted, self._on_turn_completed),
            (SystemEvent, self._on_system_event),
            (VoiceGuideQueueChanged, self._on_voice_guide_queue_changed),
        ]
        for event_type, handler in subscriptions:
            self._bus.subscribe(event_type, handler)
        return subscriptions

    async def _on_warmup_started(self, event: WarmupStarted) -> None:
        del event
        await self._transition(RuntimeState.WARMING, key="warming_model")

    async def _on_warmup_completed(self, event: WarmupCompleted) -> None:
        # A failed warm-up already surfaces as a WARN system event; the
        # engine keeps accepting input either way, so the orb goes to its
        # ready state regardless (pre-tracker behavior preserved).
        del event
        await self._transition(self._ready_state, key="ready_to_listen")

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
        await self._transition(self._ready_state, key="ready_to_listen")

    async def _on_system_event(self, event: SystemEvent) -> None:
        if event.level is EventLevel.ERROR:
            await self._transition(RuntimeState.ERROR, text=event.message)

    async def _on_voice_guide_queue_changed(
        self, event: VoiceGuideQueueChanged
    ) -> None:
        # Only a real change counts: an interrupt on an empty queue republishes
        # the state the tracker already has, and must not declare a voice-guide
        # server that never came up healthy.
        if event == self._last_queue:
            return
        self._last_queue = event
        if event.phase is VoiceGuidePhase.IDLE:
            # Items still queued: the next one publishes its own phase, and
            # resting in between would blink the orb.
            if event.length > 0:
                return
            await self._transition(self._ready_state, key="ready_to_listen")
        elif event.phase is VoiceGuidePhase.PREPARING:
            await self._transition(RuntimeState.THINKING, key="voice_guide_preparing")
        else:
            await self._transition(RuntimeState.SPEAKING, key="voice_guide_speaking")

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
