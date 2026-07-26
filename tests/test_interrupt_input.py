import asyncio

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings
from jarvis.inputs.interrupt import InterruptRequested, run_hotkey_listener


class _FakeKeyboardModule:
    """Records provider registrations and cleanup per binding - mirrors
    test_clipboard_input.py's fake."""

    def __init__(self) -> None:
        self.registered: dict[str, callable] = {}
        self.removed_handles: list[object] = []
        self._handle_by_binding: dict[str, object] = {}

    def register(self, binding, callback) -> None:
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
    hotkeys = HotkeySettings(interrupt="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()

    task = asyncio.create_task(
        run_hotkey_listener(EventBus(), hotkeys, provider=fake_kb)
    )
    await asyncio.sleep(0)

    assert set(fake_kb.registered) == {"ctrl+alt+z"}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_kb.removed_handles == [fake_kb.handle_for("ctrl+alt+z")]


async def test_hotkey_callback_publishes_interrupt_requested():
    bus = EventBus()
    received = []

    async def on_event(event: InterruptRequested) -> None:
        received.append(event)

    bus.subscribe(InterruptRequested, on_event)
    fake_kb = _FakeKeyboardModule()
    hotkeys = HotkeySettings(interrupt="ctrl+alt+z")

    task = asyncio.create_task(run_hotkey_listener(bus, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)

    assert received == [InterruptRequested()]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_two_presses_publish_two_events():
    bus = EventBus()
    received = []

    async def on_event(event: InterruptRequested) -> None:
        received.append(event)

    bus.subscribe(InterruptRequested, on_event)
    fake_kb = _FakeKeyboardModule()
    hotkeys = HotkeySettings(interrupt="ctrl+alt+z")

    task = asyncio.create_task(run_hotkey_listener(bus, hotkeys, provider=fake_kb))
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)

    assert len(received) == 2

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
