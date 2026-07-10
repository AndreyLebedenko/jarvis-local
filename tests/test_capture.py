import asyncio
import struct

import pytest

from bus import EventBus
from capture import (
    CaptureEngine,
    CaptureInput,
    RawCapture,
    ScreenshotCaptured,
    run_hotkey_listener,
)
from config import HotkeySettings


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Reads width/height straight from the PNG's IHDR chunk, avoiding a
    dependency on an image-decoding library just for this test."""
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png_bytes[16:24])
    return width, height


def _solid_rgb(width: int, height: int) -> bytes:
    return bytes([128, 64, 32]) * (width * height)


class _FakeKeyboardModule:
    """Records provider registrations and cleanup per binding."""

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


# --- CaptureEngine -----------------------------------------------------


def test_capture_full_screen_returns_expected_dimensions():
    fake_grab = lambda region: RawCapture(rgb=_solid_rgb(8, 4), width=8, height=4)
    engine = CaptureEngine(grab=fake_grab)

    screenshot = engine.capture_full_screen()

    assert screenshot.mode == "full"
    assert screenshot.width == 8
    assert screenshot.height == 4
    assert _png_dimensions(screenshot.png_bytes) == (8, 4)


def test_capture_region_returns_expected_dimensions():
    captured_region = {}

    def fake_grab(region):
        captured_region.update(region)
        return RawCapture(rgb=_solid_rgb(region["width"], region["height"]),
                           width=region["width"], height=region["height"])

    engine = CaptureEngine(grab=fake_grab)
    region = {"left": 10, "top": 20, "width": 6, "height": 3}

    screenshot = engine.capture_region(region)

    assert screenshot.mode == "region"
    assert screenshot.width == 6
    assert screenshot.height == 3
    assert _png_dimensions(screenshot.png_bytes) == (6, 3)
    assert captured_region == region


def test_capture_full_screen_passes_none_region_to_grab():
    received = []

    def fake_grab(region):
        received.append(region)
        return RawCapture(rgb=_solid_rgb(2, 2), width=2, height=2)

    CaptureEngine(grab=fake_grab).capture_full_screen()

    assert received == [None]


# --- CaptureInput (bus publishing) --------------------------------------


async def test_publish_full_screen_publishes_expected_metadata():
    bus = EventBus()
    received = []

    async def on_event(event: ScreenshotCaptured) -> None:
        received.append(event)

    bus.subscribe(ScreenshotCaptured, on_event)
    engine = CaptureEngine(grab=lambda r: RawCapture(rgb=_solid_rgb(5, 5), width=5, height=5))
    capture = CaptureInput(bus=bus, engine=engine)

    await capture.publish_full_screen()

    assert len(received) == 1
    assert received[0].mode == "full"
    assert received[0].width == 5
    assert received[0].height == 5


async def test_publish_region_publishes_expected_metadata():
    bus = EventBus()
    received = []

    async def on_event(event: ScreenshotCaptured) -> None:
        received.append(event)

    bus.subscribe(ScreenshotCaptured, on_event)

    def fake_grab(region):
        return RawCapture(rgb=_solid_rgb(region["width"], region["height"]),
                           width=region["width"], height=region["height"])

    capture = CaptureInput(bus=bus, engine=CaptureEngine(grab=fake_grab))

    await capture.publish_region({"left": 0, "top": 0, "width": 7, "height": 9})

    assert len(received) == 1
    assert received[0].mode == "region"
    assert received[0].width == 7
    assert received[0].height == 9


# --- run_hotkey_listener wiring (fake keyboard module, no real hooks) ---


async def test_hotkey_listener_registers_bindings_from_config():
    hotkeys = HotkeySettings(screenshot_full="ctrl+alt+x", screenshot_region="ctrl+alt+y")
    fake_kb = _FakeKeyboardModule()
    capture = CaptureInput(
        bus=EventBus(),
        engine=CaptureEngine(grab=lambda r: RawCapture(rgb=_solid_rgb(2, 2), width=2, height=2)),
    )

    task = asyncio.create_task(
        run_hotkey_listener(capture, hotkeys, provider=fake_kb, select_region=lambda: None)
    )
    await asyncio.sleep(0)

    assert set(fake_kb.registered) == {"ctrl+alt+x", "ctrl+alt+y"}
    expected_handles = {
        fake_kb.handle_for("ctrl+alt+x"),
        fake_kb.handle_for("ctrl+alt+y"),
    }

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert set(fake_kb.removed_handles) == expected_handles


async def test_hotkey_full_screen_callback_publishes_capture():
    bus = EventBus()
    received = []

    async def on_event(event: ScreenshotCaptured) -> None:
        received.append(event)

    bus.subscribe(ScreenshotCaptured, on_event)
    hotkeys = HotkeySettings()
    fake_kb = _FakeKeyboardModule()
    capture = CaptureInput(
        bus=bus,
        engine=CaptureEngine(grab=lambda r: RawCapture(rgb=_solid_rgb(4, 4), width=4, height=4)),
    )

    task = asyncio.create_task(
        run_hotkey_listener(capture, hotkeys, provider=fake_kb, select_region=lambda: None)
    )
    await asyncio.sleep(0)

    fake_kb.registered[hotkeys.screenshot_full]()
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].mode == "full"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_hotkey_region_callback_publishes_capture_from_selected_region():
    bus = EventBus()
    received = []

    async def on_event(event: ScreenshotCaptured) -> None:
        received.append(event)

    bus.subscribe(ScreenshotCaptured, on_event)
    hotkeys = HotkeySettings()
    fake_kb = _FakeKeyboardModule()

    def fake_grab(region):
        return RawCapture(rgb=_solid_rgb(region["width"], region["height"]),
                           width=region["width"], height=region["height"])

    capture = CaptureInput(bus=bus, engine=CaptureEngine(grab=fake_grab))
    fixed_region = {"left": 1, "top": 2, "width": 12, "height": 8}

    task = asyncio.create_task(
        run_hotkey_listener(
            capture, hotkeys, provider=fake_kb, select_region=lambda: fixed_region
        )
    )
    await asyncio.sleep(0)

    fake_kb.registered[hotkeys.screenshot_region]()
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].mode == "region"
    assert received[0].width == 12
    assert received[0].height == 8

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_hotkey_region_callback_skips_zero_size_selection():
    bus = EventBus()
    received = []

    async def on_event(event: ScreenshotCaptured) -> None:
        received.append(event)

    bus.subscribe(ScreenshotCaptured, on_event)
    hotkeys = HotkeySettings()
    fake_kb = _FakeKeyboardModule()
    capture = CaptureInput(
        bus=bus,
        engine=CaptureEngine(grab=lambda r: RawCapture(rgb=_solid_rgb(1, 1), width=1, height=1)),
    )
    empty_region = {"left": 0, "top": 0, "width": 0, "height": 0}

    task = asyncio.create_task(
        run_hotkey_listener(
            capture, hotkeys, provider=fake_kb, select_region=lambda: empty_region
        )
    )
    await asyncio.sleep(0)

    fake_kb.registered[hotkeys.screenshot_region]()
    await asyncio.sleep(0.05)

    assert received == []

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
