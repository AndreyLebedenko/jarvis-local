#!/usr/bin/env python3
"""Manual handoff for the v1.2.10 UI transport.

This check starts the real loopback HTTP+WebSocket server inside the engine
asyncio loop, opens both WebView2 windows on server URLs, and cycles the
same state projection that Chrome receives. The printed console URL can be
opened in Chrome in parallel; it contains the one-time process token.

Usage:
  python manual/manual_check_status_console.py

Manual checklist:
  1. Confirm the Status Console and touchstrip look unchanged from the
     pre-transport reference and both show the cycling states.
  2. Open the printed URL in Chrome. Confirm Chrome receives the same state,
     Think/visibility/reset/shutdown controls work, and the hello identities
     are status-console and touchstrip in the terminal log.
  3. Stop the server from a debugger or add a temporary stop call, confirm
     both surfaces show their offline indicator and do not present stale state
     as live. Restore the server and confirm automatic reconnect plus a fresh
     snapshot.
  4. Exercise Think, Open/Hidden, context reset, module reset, and guarded
     shutdown. Close the desktop window to verify the clean engine shutdown.

The real windows, WebView2, browser, microphone, speakers, and local Ollama
are human-run checks. This script intentionally uses no external network
endpoint; only the configured local Ollama path is used by the normal engine.
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bus import EventBus
from config import load_settings
from main import ConversationHistory
from status_console import StatusConsoleApi, StatusConsoleWindow, TouchstripWindow
from system_log import publish_system_event
from thinking_mode import ThinkingModeState
from ui_contract import EventLevel, RuntimeState
from ui_transport import UiStateStore, UiTransportServer
from visibility_mode import VisibilityModeState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STATE_CYCLE = list(RuntimeState)
SAMPLE_EVENTS = [
    ("WARMUP", EventLevel.INFO, "Warm-up request succeeded", "Прогрев модели завершён"),
    ("HOTKEY", EventLevel.INFO, "Thinking mode enabled", "Режим мышления включён"),
    ("HOTKEY", EventLevel.INFO, "Microphone asleep", "Микрофон усыплён"),
    ("WARMUP", EventLevel.WARN, "Warm-up request slow", "Прогрев модели занял дольше обычного"),
    ("ENGINE", EventLevel.ERROR, "Backend request failed", "Ошибка запроса к модели"),
]


@dataclass
class DemoContext:
    api: StatusConsoleApi
    bus: EventBus
    transport: UiTransportServer
    shutdown_event: asyncio.Event


async def _run_demo_cycle_async(ctx: DemoContext) -> None:
    i = 0
    while not ctx.shutdown_event.is_set():
        state = STATE_CYCLE[i % len(STATE_CYCLE)]
        ctx.transport.set_runtime_state(state)
        source, level, log_message, ui_message = SAMPLE_EVENTS[i % len(SAMPLE_EVENTS)]
        await publish_system_event(ctx.bus, logger, source, level, log_message, ui_message)
        i += 1
        try:
            await asyncio.wait_for(ctx.shutdown_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            continue


def _build_demo_context(settings) -> DemoContext:
    bus = EventBus()
    thinking_mode = ThinkingModeState(bus=bus)
    visibility_mode = VisibilityModeState(bus=bus)
    api = StatusConsoleApi(
        thinking_mode=thinking_mode,
        history=ConversationHistory(),
        bus=bus,
        logger=logger,
        visibility_mode=visibility_mode,
        settings=settings,
    )
    shutdown_event = asyncio.Event()
    api.set_shutdown_event(shutdown_event)
    transport = UiTransportServer(
        bus,
        api,
        state=UiStateStore(
            model_label=settings.backend.model,
            thinking_enabled=thinking_mode.is_enabled,
            visibility_mode=visibility_mode.mode,
        ),
        logger=logger,
    )
    return DemoContext(api=api, bus=bus, transport=transport, shutdown_event=shutdown_event)


async def _run_manual_session(
    context: DemoContext,
    console: StatusConsoleWindow,
    touchstrip: TouchstripWindow,
) -> None:
    info = await context.transport.start()
    console.load_url(info.url)
    touchstrip.load_url(info.touchstrip_url)
    print(f"Chrome URL: {info.url}")
    print("Cycle states are running. Close the desktop window or use shutdown to stop.")
    try:
        await _run_demo_cycle_async(context)
    finally:
        await context.transport.stop()
        touchstrip.close()
        console.close()


def main() -> None:
    settings = load_settings()
    import webview
    context = _build_demo_context(settings)
    console = StatusConsoleWindow()
    touchstrip = TouchstripWindow()
    console.create(on_closed=context.api.request_shutdown)
    touchstrip.create()

    def start_session() -> None:
        asyncio.run(_run_manual_session(context, console, touchstrip))

    webview.start(start_session)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
