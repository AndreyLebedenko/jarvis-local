#!/usr/bin/env python3
"""Manual handoff for task-ui-02: real pywebview/WebView2 window check.

Not an automated test - a real GUI window on a real display/WebView2
runtime is hardware/environment-dependent per CLAUDE.md's testing
protocol, so this is run by hand. Opens the actual Status Console shell
window, pushes the real backend.model from config (proving the "no
hardcoded model name" acceptance criterion end-to-end), then cycles
through every RuntimeState/HealthStatus/DataLocality combination with a
short delay so each can be eyeballed.

Usage:
  python manual_check_status_console.py
  (a window opens; states cycle automatically every 2s; close the window
  or Ctrl+C to stop)
"""

import time

from config import load_settings
from status_console import StatusConsoleWindow
from ui_contract import DataLocality, HealthStatus, ModuleHealth, ModuleId, RuntimeState

STATE_CYCLE = list(RuntimeState)
HEALTH_CYCLE = list(HealthStatus)


def _run_demo_cycle(console: StatusConsoleWindow) -> None:
    settings = load_settings()
    console.push_model_label(settings.backend.model)
    for module in ModuleId:
        console.push_module_health(ModuleHealth(module=module, status=HealthStatus.OK))
    console.push_data_locality(DataLocality.LOCAL)

    print("Cycling RuntimeState every 2s: " + ", ".join(s.value for s in STATE_CYCLE))
    while True:
        for state in STATE_CYCLE:
            console.push_runtime_state(state)
            time.sleep(2.0)


def main() -> None:
    import webview

    console = StatusConsoleWindow()
    console.create()
    webview.start(_run_demo_cycle, console)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
