"""Hotkey-triggered screen capture via mss.

CaptureEngine is pure capture logic: given a region (or None for the
full primary monitor), grabs raw pixels through an injectable grab
function and encodes them to PNG. This is what's testable with a fake
screen buffer, no real display required.

Hotkey listening and interactive region selection both require a real
display/keyboard and are covered by the manual handoff, not automated
tests - but they feed the same CaptureEngine/CaptureInput used by the
fixture tests, per this module's task card.

OCR itself is out of scope (day-0 verified fact: the model reads screen
text at request time); this module only produces the PNG.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import mss
import mss.tools

from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings
from jarvis.inputs.hotkeys import HotkeyProvider, run_hotkey_provider

Region = dict[str, int]  # {"left": int, "top": int, "width": int, "height": int}


@dataclass(frozen=True)
class RawCapture:
    rgb: bytes
    width: int
    height: int


@dataclass(frozen=True)
class ScreenshotCaptured:
    png_bytes: bytes
    mode: str
    width: int
    height: int


GrabFn = Callable[[Region | None], RawCapture]


def _default_grab(region: Region | None) -> RawCapture:
    with mss.mss() as sct:
        target = region if region is not None else sct.monitors[1]
        shot = sct.grab(target)
        return RawCapture(rgb=shot.rgb, width=shot.size[0], height=shot.size[1])


class CaptureEngine:
    def __init__(self, grab: GrabFn | None = None) -> None:
        self._grab = grab or _default_grab

    def capture_full_screen(self) -> ScreenshotCaptured:
        return self._encode(self._grab(None), mode="full")

    def capture_region(self, region: Region) -> ScreenshotCaptured:
        return self._encode(self._grab(region), mode="region")

    @staticmethod
    def _encode(raw: RawCapture, mode: str) -> ScreenshotCaptured:
        png_bytes = mss.tools.to_png(raw.rgb, (raw.width, raw.height))
        return ScreenshotCaptured(
            png_bytes=png_bytes, mode=mode, width=raw.width, height=raw.height
        )


class CaptureInput:
    def __init__(self, bus: EventBus, engine: CaptureEngine) -> None:
        self._bus = bus
        self._engine = engine

    async def publish_full_screen(self) -> None:
        screenshot = await asyncio.to_thread(self._engine.capture_full_screen)
        await self._bus.publish(ScreenshotCaptured, screenshot)

    async def publish_region(self, region: Region) -> None:
        screenshot = await asyncio.to_thread(self._engine.capture_region, region)
        await self._bus.publish(ScreenshotCaptured, screenshot)


def select_region_interactively() -> Region | None:
    """Shows a full-screen transparent overlay; the user drags a
    rectangle with the mouse, Escape cancels. Returns the selected
    region, or None if cancelled. Blocking - display-dependent, not
    automated-tested.
    """
    import tkinter as tk

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, cursor="cross", bg="grey")
    canvas.pack(fill=tk.BOTH, expand=True)

    start: dict[str, int] = {}
    result: dict[str, Region] = {}
    rect_id: list[int | None] = [None]

    def on_press(event: "tk.Event") -> None:
        start["x"], start["y"] = event.x, event.y

    def on_drag(event: "tk.Event") -> None:
        # Verified live: a release/drag can arrive without a preceding
        # press having set `start` (suspected Tk thread-safety issue -
        # see tasks/bug_reports/ - this overlay runs on the keyboard
        # library's callback thread, not the main thread Tkinter expects).
        # Ignoring an out-of-sequence event is harmless: worst case the
        # user's drag doesn't show a rectangle for one frame.
        if "x" not in start:
            return
        if rect_id[0] is not None:
            canvas.delete(rect_id[0])
        rect_id[0] = canvas.create_rectangle(
            start["x"], start["y"], event.x, event.y, outline="red", width=2
        )

    def on_release(event: "tk.Event") -> None:
        if "x" not in start:
            return
        x0, y0 = start["x"], start["y"]
        x1, y1 = event.x, event.y
        result["region"] = {
            "left": min(x0, x1),
            "top": min(y0, y1),
            "width": abs(x1 - x0),
            "height": abs(y1 - y0),
        }
        root.quit()

    def on_escape(_event: "tk.Event") -> None:
        root.quit()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.mainloop()
    root.destroy()
    return result.get("region")


async def run_hotkey_listener(
    capture: CaptureInput,
    hotkeys: HotkeySettings,
    provider: HotkeyProvider | None = None,
    select_region: Callable[[], Region | None] = select_region_interactively,
) -> None:
    """Binds hotkeys.screenshot_full/screenshot_region to real global
    hotkeys; publishes a screenshot on each trigger. Runs until
    cancelled. Hardware/display-dependent in its default form, but
    provider and select_region are injectable so the wiring
    itself (config-driven bindings -> callback -> bus publish) is
    testable without a real keyboard hook or display.
    """
    loop = asyncio.get_running_loop()

    def on_full_screen() -> None:
        asyncio.run_coroutine_threadsafe(capture.publish_full_screen(), loop)

    def on_region() -> None:
        region = select_region()
        if region is not None and region["width"] > 0 and region["height"] > 0:
            asyncio.run_coroutine_threadsafe(capture.publish_region(region), loop)

    await run_hotkey_provider(
        [
            (hotkeys.screenshot_full, on_full_screen),
            (hotkeys.screenshot_region, on_region),
        ],
        provider,
    )
