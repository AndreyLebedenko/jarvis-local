"""Thinking-mode runtime state and hotkey input.

Owns whether Ollama thinking mode is enabled for future turns (see
PROJECT.md's thinking-mode story: the hotkey toggles a persistent state for
the *next* accepted request, not the currently in-flight one). This module
does not know about OllamaBackend's payload shape or TTS - task-13 reads
ThinkingModeState.is_enabled at turn-construction time and passes it into
backend.py's thinking_enabled parameter; that wiring is out of this task's
scope.

run_hotkey_listener() mirrors audio_in.py's run_hotkey_listener /
clipboard_input.py's run_hotkey_listener: config-driven binding, injectable
keyboard module, no direct SoundCuePlayer dependency (main.py decides what
to do with ThinkingModeToggled, same split used for every other cue).

ThinkingModeState.toggle() flips and publishes with no `await` between the
read and the write, same race-avoidance rule as AudioInput.
toggle_user_sleep() (task-10's review): the whole read-decide-write must
happen synchronously on the event loop so two rapid hotkey presses (both
scheduled from the keyboard package's own callback thread via
run_coroutine_threadsafe) can never both observe the same stale state and
schedule the same transition twice instead of toggling twice.
"""

import asyncio
from dataclasses import dataclass

from bus import EventBus
from config import HotkeySettings
from hotkey_provider import HotkeyProvider, run_hotkey_provider


@dataclass(frozen=True)
class ThinkingModeToggled:
    is_enabled: bool


class ThinkingModeState:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def toggle(self) -> None:
        self._enabled = not self._enabled
        await self._bus.publish(
            ThinkingModeToggled, ThinkingModeToggled(is_enabled=self._enabled)
        )


async def run_hotkey_listener(
    state: ThinkingModeState,
    hotkeys: HotkeySettings,
    provider: HotkeyProvider | None = None,
) -> None:
    """Binds hotkeys.thinking_toggle to a real global hotkey; each press
    calls state.toggle(). Runs until cancelled. Hardware-dependent in its
    default form, but provider is injectable so the wiring itself is
    testable without a real keyboard hook.

    Deliberately does not read state.is_enabled here to decide what to do:
    that decision must happen inside toggle() itself, on the event loop -
    reading state in this callback (which runs on the keyboard package's
    own thread) would race against the event loop's own mutation, same bug
    class task-10's review caught for the mic-sleep hotkey.
    """
    loop = asyncio.get_running_loop()

    def on_toggle() -> None:
        asyncio.run_coroutine_threadsafe(state.toggle(), loop)

    await run_hotkey_provider([(hotkeys.thinking_toggle, on_toggle)], provider)
