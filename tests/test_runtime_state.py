"""RuntimeStateTracker: the single owner of RuntimeState transitions."""

import time

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
from jarvis.ui.runtime_state import RuntimeStateChanged, RuntimeStateTracker


def _system_event(level: EventLevel, message: str) -> SystemEvent:
    return SystemEvent(
        timestamp=time.time(), source="TEST", level=level, message=message
    )


class _Recorder:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[RuntimeStateChanged] = []
        bus.subscribe(RuntimeStateChanged, self._on_changed)

    async def _on_changed(self, event: RuntimeStateChanged) -> None:
        self.events.append(event)


def _tracked_bus() -> tuple[EventBus, _Recorder]:
    bus = EventBus()
    RuntimeStateTracker(bus).subscribe()
    return bus, _Recorder(bus)


async def test_warmup_lifecycle_moves_warming_then_listening():
    bus, recorder = _tracked_bus()

    await bus.publish(WarmupStarted, WarmupStarted())
    await bus.publish(WarmupCompleted, WarmupCompleted(succeeded=True))

    assert [event.state for event in recorder.events] == [
        RuntimeState.WARMING,
        RuntimeState.LISTENING,
    ]
    assert recorder.events[0].substatus_key == "warming_model"
    assert recorder.events[1].substatus_key == "ready_to_listen"


async def test_failed_warmup_still_reaches_listening():
    bus, recorder = _tracked_bus()

    await bus.publish(WarmupCompleted, WarmupCompleted(succeeded=False))

    assert recorder.events[-1].state is RuntimeState.LISTENING


async def test_turn_source_selects_the_thinking_substatus():
    bus, recorder = _tracked_bus()

    await bus.publish(TurnAccepted, TurnAccepted(source=TurnSource.VOICE))
    await bus.publish(TurnCompleted, TurnCompleted())
    await bus.publish(TurnAccepted, TurnAccepted(source=TurnSource.TEXT))
    await bus.publish(TurnCompleted, TurnCompleted())
    await bus.publish(TurnAccepted, TurnAccepted(source=TurnSource.TEXT_INPUT))
    await bus.publish(TurnCompleted, TurnCompleted())
    await bus.publish(TurnAccepted, TurnAccepted(source=TurnSource.ATTACHMENT))

    thinking = [e for e in recorder.events if e.state is RuntimeState.THINKING]
    assert [e.substatus_key for e in thinking] == [
        "processing_voice",
        "processing_text",
        "processing_text",
        "processing_attachment",
    ]


async def test_text_input_turn_reaches_speaking_state():
    bus, recorder = _tracked_bus()

    await bus.publish(TurnAccepted, TurnAccepted(source=TurnSource.TEXT_INPUT))
    await bus.publish(ResponseToken, ResponseToken(text="x"))

    assert [event.state for event in recorder.events] == [
        RuntimeState.THINKING,
        RuntimeState.SPEAKING,
    ]
    assert recorder.events[0].substatus_key == "processing_text"
    assert recorder.events[1].substatus_key == "speaking_response"


async def test_token_flood_publishes_speaking_once():
    bus, recorder = _tracked_bus()

    await bus.publish(TurnAccepted, TurnAccepted(source=TurnSource.VOICE))
    for _ in range(5):
        await bus.publish(ResponseToken, ResponseToken(text="x"))

    assert [event.state for event in recorder.events] == [
        RuntimeState.THINKING,
        RuntimeState.SPEAKING,
    ]
    assert recorder.events[-1].substatus_key == "speaking_response"


async def test_warmup_tokens_do_not_announce_speaking():
    """The warm-up request streams ResponseToken through the same bus;
    SPEAKING must only follow an accepted turn."""
    bus, recorder = _tracked_bus()

    await bus.publish(WarmupStarted, WarmupStarted())
    await bus.publish(ResponseToken, ResponseToken(text="warmup"))
    await bus.publish(WarmupCompleted, WarmupCompleted(succeeded=True))
    await bus.publish(ResponseToken, ResponseToken(text="stray"))

    assert [event.state for event in recorder.events] == [
        RuntimeState.WARMING,
        RuntimeState.LISTENING,
    ]


async def test_turn_completed_returns_to_listening_after_speaking():
    bus, recorder = _tracked_bus()

    await bus.publish(TurnAccepted, TurnAccepted(source=TurnSource.VOICE))
    await bus.publish(ResponseToken, ResponseToken(text="x"))
    await bus.publish(TurnCompleted, TurnCompleted())

    assert [event.state for event in recorder.events] == [
        RuntimeState.THINKING,
        RuntimeState.SPEAKING,
        RuntimeState.LISTENING,
    ]


async def test_error_system_event_carries_its_message_as_literal_text():
    bus, recorder = _tracked_bus()

    await bus.publish(SystemEvent, _system_event(EventLevel.ERROR, "boom"))

    assert recorder.events == [
        RuntimeStateChanged(
            state=RuntimeState.ERROR, substatus_key=None, substatus_text="boom"
        )
    ]


async def test_non_error_system_events_do_not_change_state():
    bus, recorder = _tracked_bus()

    await bus.publish(SystemEvent, _system_event(EventLevel.INFO, "fine"))
    await bus.publish(SystemEvent, _system_event(EventLevel.WARN, "hmm"))

    assert recorder.events == []


async def test_repeated_error_with_new_message_is_republished():
    bus, recorder = _tracked_bus()

    await bus.publish(SystemEvent, _system_event(EventLevel.ERROR, "first"))
    await bus.publish(SystemEvent, _system_event(EventLevel.ERROR, "first"))
    await bus.publish(SystemEvent, _system_event(EventLevel.ERROR, "second"))

    assert [event.substatus_text for event in recorder.events] == ["first", "second"]
