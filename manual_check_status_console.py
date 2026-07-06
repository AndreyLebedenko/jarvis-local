#!/usr/bin/env python3
"""Manual handoff for task-ui-02/task-ui-03: real pywebview/WebView2 window
check, including live system events.

Not an automated test - a real GUI window on a real display/WebView2
runtime is hardware/environment-dependent per CLAUDE.md's testing
protocol, so this is run by hand. Opens the actual Status Console shell
window, pushes the real backend.model from config (proving the "no
hardcoded model name" acceptance criterion end-to-end), cycles through
every RuntimeState/HealthStatus/DataLocality combination, and publishes a
handful of SystemEvents through the real bus + system_log.
publish_system_event() (the same function main.py's warm_up()/
_on_mic_sleep_toggled()/_on_thinking_mode_toggled() call) so the events
panel can be eyeballed end-to-end, not just via demo.html's synthetic
button clicks.

Usage:
  python manual_check_status_console.py
  (a window opens; states/events cycle automatically; close the window or
  Ctrl+C to stop)
"""

import asyncio
import logging

from bus import EventBus
from config import load_settings
from status_console import StatusConsoleWindow
from system_log import publish_system_event
from ui_contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STATE_CYCLE = list(RuntimeState)

_SAMPLE_EVENTS = [
    ("WARMUP", EventLevel.INFO, "Warm-up request succeeded", "Прогрев модели завершён"),
    ("HOTKEY", EventLevel.INFO, "Thinking mode enabled", "Режим мышления включён"),
    ("HOTKEY", EventLevel.INFO, "Microphone asleep", "Микрофон усыплён"),
    ("WARMUP", EventLevel.WARN, "Warm-up request slow", "Прогрев модели занял дольше обычного"),
    ("ENGINE", EventLevel.ERROR, "Backend request failed", "Ошибка запроса к модели"),
]


async def _run_demo_cycle_async(console: StatusConsoleWindow) -> None:
    bus = EventBus()

    async def on_system_event(event: SystemEvent) -> None:
        console.push_system_event(event)

    bus.subscribe(SystemEvent, on_system_event)

    settings = load_settings()
    console.push_model_label(settings.backend.model)
    for module in ModuleId:
        console.push_module_health(ModuleHealth(module=module, status=HealthStatus.OK))
    console.push_data_locality(DataLocality.LOCAL)

    print("Cycling RuntimeState + sample SystemEvents every 2s.")
    i = 0
    while True:
        console.push_runtime_state(STATE_CYCLE[i % len(STATE_CYCLE)])
        source, level, log_message, ui_message = _SAMPLE_EVENTS[i % len(_SAMPLE_EVENTS)]
        await publish_system_event(bus, logger, source, level, log_message, ui_message)
        i += 1
        await asyncio.sleep(2.0)


def _run_demo_cycle(console: StatusConsoleWindow) -> None:
    asyncio.run(_run_demo_cycle_async(console))


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
