#!/usr/bin/env python3
"""Manual handoff for task-ui-02 through task-ui-06: real pywebview/
WebView2 window check, including live system events, the Think/reset/
visibility-mode controls' real JS -> Python round trip, and the touchstrip
glance surface sharing the same engine state as the desktop window.

Not an automated test - a real GUI window on a real display/WebView2
runtime is hardware/environment-dependent per CLAUDE.md's testing
protocol, so this is run by hand. Opens both the desktop Status Console
window and the touchstrip window side by side, pushes the real
backend.model from config (proving the "no hardcoded model name"
acceptance criterion end-to-end), cycles through every RuntimeState/
HealthStatus/DataLocality combination on both windows, publishes a handful
of SystemEvents through the real bus + system_log.publish_system_event()
(desktop only - the touchstrip has no event log by design), and wires a
real StatusConsoleApi, shared by both windows, so clicking the Think
switch/reset controls/Open-Hidden toggle on *either* window is reflected
on the other.

Usage:
  python manual_check_status_console.py
  (two windows open; states/events cycle automatically; click the Think
  switch, reset buttons, and Open/Hidden toggle on either window and
  confirm the other one updates too - Hidden should replace the desktop's
  vision chip detail text and never change either window's locality
  display; close both windows to stop)

Note: Ctrl+C in the terminal will not reliably stop this script.
webview.start()'s native GUI loop (WebView2/EdgeChromium via pythonnet on
Windows) owns the main thread and does not hand control back to the
Python interpreter between messages, so there is no point at which
SIGINT gets checked - a CPython/embedded-native-loop limitation, not a
bug in this script. Close the windows themselves (or use Task Manager if
unresponsive) instead of relying on Ctrl+C.
"""

import asyncio
import logging
from dataclasses import dataclass

from bus import EventBus
from config import load_settings
from main import ConversationHistory
from status_console import StatusConsoleApi, StatusConsoleWindow, TouchstripWindow
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
    touchstrip: TouchstripWindow
    api: StatusConsoleApi
    bus: EventBus
    thinking_mode: ThinkingModeState
    visibility_mode: VisibilityModeState


async def _run_demo_cycle_async(ctx: DemoContext) -> None:
    # The real asyncio loop only exists from here on - see StatusConsoleApi's
    # docstring for why set_loop() happens here, not in main().
    ctx.api.set_loop(asyncio.get_running_loop())

    async def on_system_event(event: SystemEvent) -> None:
        ctx.console.push_system_event(event)  # touchstrip has no event log

    async def on_thinking_toggled(event: ThinkingModeToggled) -> None:
        ctx.console.push_thinking_mode(event.is_enabled)
        ctx.touchstrip.push_thinking_mode(event.is_enabled)

    async def on_visibility_mode_changed(event: VisibilityModeChanged) -> None:
        ctx.console.push_visibility_mode(event.mode)
        ctx.touchstrip.push_visibility_mode(event.mode)

    ctx.bus.subscribe(SystemEvent, on_system_event)
    ctx.bus.subscribe(ThinkingModeToggled, on_thinking_toggled)
    ctx.bus.subscribe(VisibilityModeChanged, on_visibility_mode_changed)

    settings = load_settings()
    for window in (ctx.console, ctx.touchstrip):
        window.push_model_label(settings.backend.model)
        for module in ModuleId:
            window.push_module_health(ModuleHealth(module=module, status=HealthStatus.OK))
        window.push_data_locality(DataLocality.LOCAL)
        window.push_thinking_mode(ctx.thinking_mode.is_enabled)
        window.push_visibility_mode(ctx.visibility_mode.mode)
    # A fake capture detail, so clicking Hidden on the desktop window has
    # something visible to replace (see app.js's _renderVisionChipMeta()) -
    # the touchstrip never shows per-module detail text at all.
    ctx.console.push_module_health(
        ModuleHealth(module=ModuleId.VISION, status=HealthStatus.OK, detail="1200x800 @ демо")
    )

    print("Cycling RuntimeState + sample SystemEvents every 2s on both windows.")
    print("Click Think / reset / Open-Hidden on either window and confirm the other updates too.")
    i = 0
    while True:
        state = STATE_CYCLE[i % len(STATE_CYCLE)]
        ctx.console.push_runtime_state(state)
        ctx.touchstrip.push_runtime_state(state)
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
    # Real settings (not a fake/default Settings()) so the config menu's
    # model selector points at the real local Ollama endpoint and the
    # microphone selector's "current" reflects this machine's actual
    # config.toml/config.ui.toml, matching a real python main.py
    # --status-console run - see story-v1.2.4-task-3-config-menu-
    # iteration-1.md's manual handoff.
    api = StatusConsoleApi(
        thinking_mode=thinking_mode,
        history=history,
        bus=bus,
        logger=logger,
        visibility_mode=visibility_mode,
        settings=load_settings(),
    )

    console = StatusConsoleWindow()
    console.create(js_api=api)
    touchstrip = TouchstripWindow()
    touchstrip.create(js_api=api)  # same api instance - one shared engine state

    ctx = DemoContext(
        console=console,
        touchstrip=touchstrip,
        api=api,
        bus=bus,
        thinking_mode=thinking_mode,
        visibility_mode=visibility_mode,
    )
    webview.start(_run_demo_cycle, ctx)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
