import asyncio

import pytest

from bus import EventBus
from config import ClipboardSettings, HotkeySettings
from clipboard_input import ClipboardSubmitted, read_clipboard_submission, run_hotkey_listener


def test_reads_clean_short_text_unchanged():
    settings = ClipboardSettings(max_chars=100)

    event = read_clipboard_submission(settings, read_clipboard=lambda: "print('hi')")

    assert event == ClipboardSubmitted(text="print('hi')", truncated=False, is_empty=False)


def test_truncates_text_over_max_chars_with_visible_marker():
    settings = ClipboardSettings(max_chars=10)
    long_text = "x" * 50

    event = read_clipboard_submission(settings, read_clipboard=lambda: long_text)

    assert event.truncated is True
    assert event.is_empty is False
    assert event.text.startswith("x" * 10)
    assert "10" in event.text  # the marker names the character limit
    assert len(event.text) > 10  # marker text appended, not just a hard cut


def test_text_at_exactly_max_chars_is_not_truncated():
    settings = ClipboardSettings(max_chars=10)
    text = "x" * 10

    event = read_clipboard_submission(settings, read_clipboard=lambda: text)

    assert event == ClipboardSubmitted(text=text, truncated=False, is_empty=False)


def test_empty_clipboard_reports_is_empty():
    settings = ClipboardSettings()

    event = read_clipboard_submission(settings, read_clipboard=lambda: "")

    assert event == ClipboardSubmitted(text="", truncated=False, is_empty=True)


def test_whitespace_only_clipboard_reports_is_empty():
    settings = ClipboardSettings()

    event = read_clipboard_submission(settings, read_clipboard=lambda: "   \n\t  ")

    assert event.is_empty is True


# --- task-10: real hotkey listener --------------------------------------


class _FakeKeyboardModule:
    """Mirrors capture.py's test fake and the real keyboard package's
    contract: remove_hotkey() must be called with the value add_hotkey()
    returned, not the original binding string."""

    def __init__(self) -> None:
        self.registered: dict[str, callable] = {}
        self.removed_handles: list[object] = []
        self._handle_by_binding: dict[str, object] = {}

    def add_hotkey(self, binding, callback):
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
    hotkeys = HotkeySettings(clipboard_submit="ctrl+alt+z")
    fake_kb = _FakeKeyboardModule()

    task = asyncio.create_task(
        run_hotkey_listener(
            EventBus(), hotkeys, ClipboardSettings(), keyboard_module=fake_kb
        )
    )
    await asyncio.sleep(0)

    assert set(fake_kb.registered) == {"ctrl+alt+z"}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_kb.removed_handles == [fake_kb.handle_for("ctrl+alt+z")]


async def test_hotkey_callback_publishes_clipboard_submitted():
    bus = EventBus()
    received = []

    async def on_event(event: ClipboardSubmitted) -> None:
        received.append(event)

    bus.subscribe(ClipboardSubmitted, on_event)
    fake_kb = _FakeKeyboardModule()
    hotkeys = HotkeySettings(clipboard_submit="ctrl+alt+z")

    task = asyncio.create_task(
        run_hotkey_listener(
            bus,
            hotkeys,
            ClipboardSettings(),
            keyboard_module=fake_kb,
            read_clipboard=lambda: "hello from clipboard",
        )
    )
    await asyncio.sleep(0)

    fake_kb.registered["ctrl+alt+z"]()
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].text == "hello from clipboard"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
