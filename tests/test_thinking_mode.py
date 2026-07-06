import asyncio
from collections.abc import Callable

import pytest

from bus import EventBus
from config import HotkeySettings
from thinking_mode import ThinkingModeState, ThinkingModeToggled, run_hotkey_listener


def test_state_starts_disabled_by_default():
    state = ThinkingModeState(bus=EventBus())

    assert state.is_enabled is False


async def test_toggle_flips_state_and_publishes_new_value():
    bus = EventBus()
    received = []

    async def on_event(event: ThinkingModeToggled) -> None:
        received.append(event)

    bus.subscribe(ThinkingModeToggled, on_event)
    state = ThinkingModeState(bus=bus)

    await state.toggle()
    await state.toggle()

    assert state.is_enabled is False
    assert received == [
        ThinkingModeToggled(is_enabled=True),
        ThinkingModeToggled(is_enabled=False),
    ]


class _FakeKeyboardModule:
    """Mirrors capture.py/audio_in.py/clipboard_input.py's test fake and the
    real keyboard package's contract: remove_hotkey() must be called with
    the value add_hotkey() returned, not the original binding string."""

    def __init__(self) -> None:
        self.registered: dict[str, Callable[[], None]] = {}
        self.removed_handles: list[object] = []
        self._handle_by_binding: dict[str, object] = {}

    def add_hotkey(self, binding: str, callback: Callable[[], None]) -> object:
        self.registered[binding] = callback
        handle = object()
        self._handle_by_binding[binding] = handle
        return handle

    def remove_hotkey(self, handle) -> None:
        valid_handles = set(self._handle_by_binding.values())
        assert handle in valid_handles, (
            f"remove_hotkey called with {handle!r}, which is not a handle "
            "add_hotkey returned"
        )
        self.removed_handles.append(handle)

    def handle_for(self, binding: str) -> object:
        return self._handle_by_binding[binding]


async def test_hotkey_listener_registers_binding_from_config():
    hotkeys = HotkeySettings(thinking_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    state = ThinkingModeState(bus=EventBus())

    task = asyncio.create_task(
        run_hotkey_listener(state, hotkeys, keyboard_module=fake_kb)
    )
    await asyncio.sleep(0)

    assert set(fake_kb.registered) == {"ctrl+alt+z"}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_kb.removed_handles == [fake_kb.handle_for("ctrl+alt+z")]


async def test_hotkey_press_schedules_exactly_one_toggle():
    hotkeys = HotkeySettings(thinking_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    state = ThinkingModeState(bus=EventBus())
    assert state.is_enabled is False

    task = asyncio.create_task(
        run_hotkey_listener(state, hotkeys, keyboard_module=fake_kb)
    )
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)
    assert state.is_enabled is True

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)
    assert state.is_enabled is False

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_two_rapid_hotkey_presses_toggle_twice_not_the_same_transition_twice():
    """Regression for the same race class task-10's review caught for the
    mic-sleep hotkey: invoking the callback twice back-to-back, before
    yielding to the loop, must produce two toggles - not two schedulings
    of the same stale transition - because toggle() reads and flips state
    with no intervening await."""
    hotkeys = HotkeySettings(thinking_toggle="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()
    bus = EventBus()
    received = []

    async def on_event(event: ThinkingModeToggled) -> None:
        received.append(event)

    bus.subscribe(ThinkingModeToggled, on_event)
    state = ThinkingModeState(bus=bus)
    assert state.is_enabled is False

    task = asyncio.create_task(
        run_hotkey_listener(state, hotkeys, keyboard_module=fake_kb)
    )
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    fake_kb.registered["ctrl+alt+z"]()  # back-to-back, before either has run yet
    await asyncio.sleep(0.05)

    assert state.is_enabled is False  # toggled twice: back to the original state
    assert [event.is_enabled for event in received] == [True, False]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
