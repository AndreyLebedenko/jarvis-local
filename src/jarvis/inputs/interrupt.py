"""Interrupt hotkey - the primary, hardware-independent way to stop
Jarvis mid-response (task-v1.7.0-2).

Publishes an InterruptRequested event on each press. This module only
turns a keypress into a bus event, mirroring clipboard.py/capture.py's
run_hotkey_listener shape - config-driven binding, injectable provider
so the wiring is testable without a real keyboard hook. The actual
cancellation sequence (stop TTS, cancel the backend stream, resume the
mic) lives in app.py's _on_interrupt_requested, which owns every
App-level component this needs; this module deliberately knows nothing
about TTS, the backend, or the Orchestrator.
"""

import asyncio
from dataclasses import dataclass

from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings
from jarvis.inputs.hotkeys import HotkeyProvider, run_hotkey_provider


@dataclass(frozen=True)
class InterruptRequested:
    """A hotkey press asking to cancel the in-flight turn, if any. A
    press while Jarvis is idle is a no-op - see app.py's handler."""


async def run_hotkey_listener(
    bus: EventBus,
    hotkeys: HotkeySettings,
    provider: HotkeyProvider | None = None,
) -> None:
    """Binds hotkeys.interrupt to a real global hotkey; publishes
    InterruptRequested on each trigger. Runs until cancelled."""
    loop = asyncio.get_running_loop()

    def on_interrupt() -> None:
        asyncio.run_coroutine_threadsafe(
            bus.publish(InterruptRequested, InterruptRequested()), loop
        )

    await run_hotkey_provider([(hotkeys.interrupt, on_interrupt)], provider)
