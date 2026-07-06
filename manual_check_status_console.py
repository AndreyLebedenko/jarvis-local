#!/usr/bin/env python3
"""Manual handoff for task-ui-02/task-ui-03/task-ui-04/task-ui-05: real
pywebview/WebView2 window check, including live system events and the
Think/reset/visibility-mode controls' real JS -> Python round trip.

Not an automated test - a real GUI window on a real display/WebView2
runtime is hardware/environment-dependent per CLAUDE.md's testing
protocol, so this is run by hand. Opens the actual Status Console shell
window, pushes the real backend.model from config (proving the "no
hardcoded model name" acceptance criterion end-to-end), cycles through
every RuntimeState/HealthStatus/DataLocality combination, publishes a
handful of SystemEvents through the real bus + system_log.
publish_system_event(), and wires a real StatusConsoleApi so clicking the
Think switch/reset buttons/Open-Hidden toggle in the actual window
exercises the real ThinkingModeState/ConversationHistory/
VisibilityModeState - not demo.html's synthetic button clicks.

Usage:
  python manual_check_status_console.py
  (a window opens; states/events cycle automatically; click the Think
  switch, reset buttons, and Open/Hidden toggle to confirm the real round
  trip - Hidden should replace the vision chip's detail text and never
  change the locality badge; close the window to stop)

Note: Ctrl+C in the terminal will not reliably stop this script.
webview.start()'s native GUI loop (WebView2/EdgeChromium via pythonnet on
Windows) owns the main thread and does not hand control back to the
Python interpreter between messages, so there is no point at which
SIGINT gets checked - a CPython/embedded-native-loop limitation, not a
bug in this script. Close the window itself (or use Task Manager if it
is unresponsive) instead of relying on Ctrl+C.
"""

import asyncio
import logging
from dataclasses import dataclass

from bus import EventBus
from config import load_settings
from main import ConversationHistory
from status_console import StatusConsoleApi, StatusConsoleWindow
from system_log import publish_system_event
from thinking_mode import ThinkingModeState, ThinkingModeToggled
from ui_contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
)
from visibility_mode import VisibilityModeChanged, VisibilityModeState

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


@dataclass
class DemoContext:
    console: StatusConsoleWindow
    api: StatusConsoleApi
    bus: EventBus
    thinking_mode: ThinkingModeState
    visibility_mode: VisibilityModeState


async def _run_demo_cycle_async(ctx: DemoContext) -> None:
    # The real asyncio loop only exists from here on - see StatusConsoleApi's
    # docstring for why set_loop() happens here, not in main().
    ctx.api.set_loop(asyncio.get_running_loop())

    async def on_system_event(event: SystemEvent) -> None:
        ctx.console.push_system_event(event)

    async def on_thinking_toggled(event: ThinkingModeToggled) -> None:
        ctx.console.push_thinking_mode(event.is_enabled)

    async def on_visibility_mode_changed(event: VisibilityModeChanged) -> None:
        ctx.console.push_visibility_mode(event.mode)

    ctx.bus.subscribe(SystemEvent, on_system_event)
    ctx.bus.subscribe(ThinkingModeToggled, on_thinking_toggled)
    ctx.bus.subscribe(VisibilityModeChanged, on_visibility_mode_changed)

    settings = load_settings()
    ctx.console.push_model_label(settings.backend.model)
    for module in ModuleId:
        ctx.console.push_module_health(ModuleHealth(module=module, status=HealthStatus.OK))
    ctx.console.push_data_locality(DataLocality.LOCAL)
    ctx.console.push_thinking_mode(ctx.thinking_mode.is_enabled)
    ctx.console.push_visibility_mode(ctx.visibility_mode.mode)
    # A fake capture detail, so clicking Hidden in the real window has
    # something visible to replace (see app.js's _renderVisionChipMeta()).
    ctx.console.push_module_health(
        ModuleHealth(module=ModuleId.VISION, status=HealthStatus.OK, detail="1200x800 @ демо")
    )

    print("Cycling RuntimeState + sample SystemEvents every 2s.")
    print("Click the Think switch / reset buttons / Open-Hidden toggle to test the real round trip.")
    i = 0
    while True:
        ctx.console.push_runtime_state(STATE_CYCLE[i % len(STATE_CYCLE)])
        source, level, log_message, ui_message = _SAMPLE_EVENTS[i % len(_SAMPLE_EVENTS)]
        await publish_system_event(ctx.bus, logger, source, level, log_message, ui_message)
        i += 1
        await asyncio.sleep(2.0)


def _run_demo_cycle(ctx: DemoContext) -> None:
    asyncio.run(_run_demo_cycle_async(ctx))


def main() -> None:
    import webview

    bus = EventBus()
    thinking_mode = ThinkingModeState(bus=bus)
    visibility_mode = VisibilityModeState(bus=bus)
    history = ConversationHistory()
    api = StatusConsoleApi(
        thinking_mode=thinking_mode,
        history=history,
        bus=bus,
        logger=logger,
        visibility_mode=visibility_mode,
    )

    console = StatusConsoleWindow()
    console.create(js_api=api)
    ctx = DemoContext(
        console=console, api=api, bus=bus, thinking_mode=thinking_mode, visibility_mode=visibility_mode
    )
    webview.start(_run_demo_cycle, ctx)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
