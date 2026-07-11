#!/usr/bin/env python3
"""Human-run native hotkey registration and conflict probe.

Usage:
  python manual/manual_check_hotkey_provider.py ctrl+alt+q

Leave one copy running, then start a second copy with the same binding to
verify conflict reporting. Press the binding to verify focus-independent
dispatch. Press Ctrl+C in the owning terminal to stop and unregister it.
"""

import sys
import threading
from contextlib import suppress
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.inputs.hotkeys import WindowsHotkeyProvider


def main(binding: str) -> None:
    provider = WindowsHotkeyProvider()

    def on_hotkey() -> None:
        print(f"FIRED: {binding}", flush=True)

    provider.register(binding, on_hotkey)
    provider.start()
    print(f"REGISTERED: {binding}", flush=True)
    print("Focus another application and press the binding. Ctrl+C stops.")
    try:
        stop_check = threading.Event()
        while not stop_check.wait(timeout=0.25):
            pass
    finally:
        provider.stop()
        print(f"UNREGISTERED: {binding}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: python manual/manual_check_hotkey_provider.py <binding>"
        )
    with suppress(KeyboardInterrupt):
        main(sys.argv[1])
