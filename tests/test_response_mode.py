import asyncio
from collections.abc import Callable

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeChanged,
    ResponseModeState,
    run_hotkey_listener,
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


class _FakeKeyboardModule:
    """Records provider registrations and cleanup per binding."""

    def __init__(self) -> None:
        self.registered: dict[str, Callable[[], None]] = {}
        self.removed_handles: list[object] = []
        self._handle_by_binding: dict[str, object] = {}

    def register(self, binding: str, callback: Callable[[], None]) -> None:
        self.registered[binding] = callback
        handle = object()
        self._handle_by_binding[binding] = handle

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.removed_handles.extend(self._handle_by_binding.values())

    def handle_for(self, binding: str) -> object:
        return self._handle_by_binding[binding]


async def test_hotkey_listener_registers_binding_from_config():
    hotkeys = HotkeySettings(response_mode_toggle="ctrl+alt+o")
    fake_kb = _FakeKeyboardModule()
    state = ResponseModeState(bus=EventBus())

    task = asyncio.create_task(run_hotkey_listener(state, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    assert set(fake_kb.registered) == {"ctrl+alt+o"}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_kb.removed_handles == [fake_kb.handle_for("ctrl+alt+o")]


async def test_hotkey_press_schedules_exactly_one_cycle():
    hotkeys = HotkeySettings(response_mode_toggle="ctrl+alt+o")
    fake_kb = _FakeKeyboardModule()
    state = ResponseModeState(bus=EventBus())
    assert state.mode is ResponseMode.TEXT

    task = asyncio.create_task(run_hotkey_listener(state, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+o"]()
    await asyncio.sleep(0.05)
    assert state.mode is ResponseMode.VOICE

    fake_kb.registered["ctrl+alt+o"]()
    await asyncio.sleep(0.05)
    assert state.mode is ResponseMode.TEXT_VOICE

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_two_rapid_hotkey_presses_cycle_twice_not_the_same_transition_twice():
    """Regression for the same race class thinking_mode.py's own hotkey
    guards against: invoking the callback twice back-to-back, before
    yielding to the loop, must produce two cycles - not two schedulings of
    the same stale transition - because cycle_mode() reads and writes
    state with no intervening await."""
    hotkeys = HotkeySettings(response_mode_toggle="ctrl+alt+o")
    fake_kb = _FakeKeyboardModule()
    bus = EventBus()
    received = []

    async def on_event(event: ResponseModeChanged) -> None:
        received.append(event)

    bus.subscribe(ResponseModeChanged, on_event)
    state = ResponseModeState(bus=bus)
    assert state.mode is ResponseMode.TEXT

    task = asyncio.create_task(run_hotkey_listener(state, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+o"]()
    fake_kb.registered["ctrl+alt+o"]()  # back-to-back, before either has run yet
    await asyncio.sleep(0.05)

    # cycled twice: text -> voice -> text_voice
    assert state.mode is ResponseMode.TEXT_VOICE
    assert [event.mode for event in received] == [
        ResponseMode.VOICE,
        ResponseMode.TEXT_VOICE,
    ]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
