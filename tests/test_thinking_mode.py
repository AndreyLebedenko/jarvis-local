import asyncio
from collections.abc import Callable

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
    ReasoningLevelState,
    run_hotkey_listener,
)


def test_state_starts_at_off():
    state = ReasoningLevelState(bus=EventBus())

    assert state.level is ReasoningLevel.OFF


async def test_set_level_changes_level_and_publishes_new_value():
    bus = EventBus()
    received = []

    async def on_event(event: ReasoningLevelChanged) -> None:
        received.append(event)

    bus.subscribe(ReasoningLevelChanged, on_event)
    state = ReasoningLevelState(bus=bus)

    await state.set_level(ReasoningLevel.MEDIUM, source="UI")

    assert state.level is ReasoningLevel.MEDIUM
    assert received == [ReasoningLevelChanged(level=ReasoningLevel.MEDIUM, source="UI")]


async def test_set_level_to_the_current_value_publishes_nothing():
    bus = EventBus()
    received = []

    async def on_event(event: ReasoningLevelChanged) -> None:
        received.append(event)

    bus.subscribe(ReasoningLevelChanged, on_event)
    state = ReasoningLevelState(bus=bus)

    await state.set_level(ReasoningLevel.OFF, source="UI")  # already off

    assert received == []


async def test_four_cycles_return_to_the_initial_state():
    state = ReasoningLevelState(bus=EventBus())

    for _ in range(4):
        await state.cycle_level(source="HOTKEY")

    assert state.level is ReasoningLevel.OFF


async def test_cycle_level_visits_off_low_medium_high_in_order():
    bus = EventBus()
    received = []

    async def on_event(event: ReasoningLevelChanged) -> None:
        received.append(event.level)

    bus.subscribe(ReasoningLevelChanged, on_event)
    state = ReasoningLevelState(bus=bus)

    for _ in range(4):
        await state.cycle_level(source="HOTKEY")

    assert received == [
        ReasoningLevel.LOW,
        ReasoningLevel.MEDIUM,
        ReasoningLevel.HIGH,
        ReasoningLevel.OFF,
    ]


async def test_cycle_level_continues_from_a_directly_set_level():
    """A hotkey cycle issued after a direct set_level() selection must
    continue the off -> low -> medium -> high -> off order from the
    directly selected level, not from wherever the cycle last left off -
    both paths share this one state owner, per the story's stop condition
    against duplicated transition logic."""
    state = ReasoningLevelState(bus=EventBus())

    await state.set_level(ReasoningLevel.MEDIUM, source="UI")
    await state.cycle_level(source="HOTKEY")

    assert state.level is ReasoningLevel.HIGH


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
    hotkeys = HotkeySettings(thinking_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    state = ReasoningLevelState(bus=EventBus())

    task = asyncio.create_task(run_hotkey_listener(state, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    assert set(fake_kb.registered) == {"ctrl+alt+z"}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_kb.removed_handles == [fake_kb.handle_for("ctrl+alt+z")]


async def test_hotkey_press_schedules_exactly_one_cycle():
    hotkeys = HotkeySettings(thinking_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    state = ReasoningLevelState(bus=EventBus())
    assert state.level is ReasoningLevel.OFF

    task = asyncio.create_task(run_hotkey_listener(state, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)
    assert state.level is ReasoningLevel.LOW

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)
    assert state.level is ReasoningLevel.MEDIUM

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_two_rapid_hotkey_presses_cycle_twice_not_the_same_transition_twice():
    """Regression for the same race class task-10's review caught for the
    mic-sleep hotkey: invoking the callback twice back-to-back, before
    yielding to the loop, must produce two cycles - not two schedulings of
    the same stale transition - because cycle_level() reads and writes
    state with no intervening await."""
    hotkeys = HotkeySettings(thinking_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    bus = EventBus()
    received = []

    async def on_event(event: ReasoningLevelChanged) -> None:
        received.append(event)

    bus.subscribe(ReasoningLevelChanged, on_event)
    state = ReasoningLevelState(bus=bus)
    assert state.level is ReasoningLevel.OFF

    task = asyncio.create_task(run_hotkey_listener(state, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    fake_kb.registered["ctrl+alt+z"]()  # back-to-back, before either has run yet
    await asyncio.sleep(0.05)

    assert state.level is ReasoningLevel.MEDIUM  # cycled twice: off -> low -> medium
    assert [event.level for event in received] == [
        ReasoningLevel.LOW,
        ReasoningLevel.MEDIUM,
    ]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
