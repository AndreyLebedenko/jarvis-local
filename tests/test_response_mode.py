import asyncio

from jarvis.core.bus import EventBus
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeChanged,
    ResponseModeState,
)


def test_state_starts_at_text_by_default():
    state = ResponseModeState(bus=EventBus())

    assert state.mode is ResponseMode.TEXT


def test_state_starts_at_the_given_initial_mode():
    """The config-seeded persistence delta from ReasoningLevelState (which
    always starts at off): build_app() passes initial_mode from
    Settings.response.mode."""
    state = ResponseModeState(bus=EventBus(), initial_mode=ResponseMode.VOICE)

    assert state.mode is ResponseMode.VOICE


async def test_set_mode_changes_mode_and_publishes_new_value():
    bus = EventBus()
    received = []

    async def on_event(event: ResponseModeChanged) -> None:
        received.append(event)

    bus.subscribe(ResponseModeChanged, on_event)
    state = ResponseModeState(bus=bus)

    await state.set_mode(ResponseMode.VOICE, source="UI")

    assert state.mode is ResponseMode.VOICE
    assert received == [ResponseModeChanged(mode=ResponseMode.VOICE, source="UI")]


async def test_set_mode_to_the_current_value_publishes_nothing():
    bus = EventBus()
    received = []

    async def on_event(event: ResponseModeChanged) -> None:
        received.append(event)

    bus.subscribe(ResponseModeChanged, on_event)
    state = ResponseModeState(bus=bus)

    await state.set_mode(ResponseMode.TEXT, source="UI")  # already text

    assert received == []


async def test_three_cycles_return_to_the_initial_state():
    state = ResponseModeState(bus=EventBus())

    for _ in range(3):
        await state.cycle_mode(source="HOTKEY")

    assert state.mode is ResponseMode.TEXT


async def test_cycle_mode_visits_voice_then_text_voice_then_text_in_order():
    bus = EventBus()
    received = []

    async def on_event(event: ResponseModeChanged) -> None:
        received.append(event.mode)

    bus.subscribe(ResponseModeChanged, on_event)
    state = ResponseModeState(bus=bus)

    for _ in range(3):
        await state.cycle_mode(source="HOTKEY")

    assert received == [
        ResponseMode.VOICE,
        ResponseMode.TEXT_VOICE,
        ResponseMode.TEXT,
    ]


async def test_cycle_mode_continues_from_a_directly_set_mode():
    """Mirrors ReasoningLevelState's own regression guard: a cycle issued
    after a direct set_mode() selection must continue the
    text -> voice -> text_voice -> text order from the selected mode, not
    from wherever cycling last left off."""
    state = ResponseModeState(bus=EventBus())

    await state.set_mode(ResponseMode.VOICE, source="UI")
    await state.cycle_mode(source="HOTKEY")

    assert state.mode is ResponseMode.TEXT_VOICE


async def test_two_rapid_direct_calls_cycle_twice_not_the_same_transition_twice():
    """Same race class as thinking_mode.py's hotkey regression: cycle_mode()
    reads and writes state with no intervening await, so two calls issued
    back-to-back (no await between them) must produce two cycles."""
    bus = EventBus()
    received = []

    async def on_event(event: ResponseModeChanged) -> None:
        received.append(event)

    bus.subscribe(ResponseModeChanged, on_event)
    state = ResponseModeState(bus=bus)

    first = asyncio.create_task(state.cycle_mode(source="HOTKEY"))
    second = asyncio.create_task(state.cycle_mode(source="HOTKEY"))  # no await above
    await first
    await second

    # cycled twice: text -> voice -> text_voice, not the same transition twice
    assert state.mode is ResponseMode.TEXT_VOICE
    assert [event.mode for event in received] == [
        ResponseMode.VOICE,
        ResponseMode.TEXT_VOICE,
    ]
