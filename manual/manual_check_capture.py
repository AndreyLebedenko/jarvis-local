#!/usr/bin/env python3
"""Manual handoff for task-06: live hotkey/display check of capture.py.

Not an automated test - hotkeys and the interactive region overlay are
hardware/display-dependent per CLAUDE.md's testing protocol, so this is
run by hand. Confirms the real full-screen hotkey triggers a capture, the
region hotkey opens the interactive selection overlay and captures just
that region, and both resulting images look correct.

The native provider's elevation behavior is verified by the v1.2.6 manual
hotkey handoff. Run this check in the privilege mode requested there.

Usage:
  python manual/manual_check_capture.py
  (press the full-screen hotkey, then the region hotkey and drag a
  rectangle, Escape cancels a region selection; Ctrl+C to stop)
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bus import EventBus
from capture import CaptureEngine, CaptureInput, ScreenshotCaptured, run_hotkey_listener
from config import load_settings

OUT_DIR = Path("manual_check_capture_out")


async def main() -> None:
    settings = load_settings()
    bus = EventBus()
    OUT_DIR.mkdir(exist_ok=True)
    count = 0

    async def on_screenshot(event: ScreenshotCaptured) -> None:
        nonlocal count
        count += 1
        out_path = OUT_DIR / f"capture_{count:03d}_{event.mode}.png"
        out_path.write_bytes(event.png_bytes)
        print(f"[{count}] {event.mode}: {event.width}x{event.height} -> {out_path}")

    bus.subscribe(ScreenshotCaptured, on_screenshot)
    capture = CaptureInput(bus=bus, engine=CaptureEngine())

    print(f"Full-screen hotkey: {settings.hotkeys.screenshot_full}")
    print(f"Region-select hotkey: {settings.hotkeys.screenshot_region}")
    print("Drag a rectangle for region select, Escape cancels it.")
    print(f"Saved screenshots land in {OUT_DIR}/. Ctrl+C to stop.\n")

    await run_hotkey_listener(capture, settings.hotkeys)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
