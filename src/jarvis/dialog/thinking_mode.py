"""Graded reasoning-level runtime state and hotkey input.

Owns the persistent reasoning level (`off`/`low`/`medium`/`high`) applied
to future turns (see PROJECT.md's graded reasoning story: the hotkey/UI
change a persistent state for the *next* accepted request, not the
currently in-flight one). This module does not know about OllamaBackend's
payload shape or TTS - main.py reads ReasoningLevelState.level at
turn-construction time and passes it into backend.py's chat(); that wiring
is out of this module's scope.

run_hotkey_listener() mirrors audio_in.py's run_hotkey_listener /
clipboard_input.py's run_hotkey_listener: config-driven binding, injectable
keyboard module, no direct SoundCuePlayer dependency (main.py decides what
to do with ReasoningLevelChanged, same split used for every other cue).

set_level()/cycle_level() publish with no `await` between the read and the
write, same race-avoidance rule as AudioInput.toggle_user_sleep() (task-10's
review): the whole read-decide-write must happen synchronously on the event
loop so two rapid hotkey presses (both scheduled from the provider's
callback thread via run_coroutine_threadsafe) can never both observe the
same stale level and schedule the same transition twice instead of cycling
twice. The same guarantee holds when a hotkey cycle and a direct UI
set_level() interleave: both go through this one state owner, and neither
method awaits before it has already written the new level.
"""

import asyncio
import enum
from dataclasses import dataclass

from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings
from jarvis.inputs.hotkeys import HotkeyProvider, run_hotkey_provider


class ReasoningLevel(enum.Enum):
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


CYCLE_ORDER: tuple[ReasoningLevel, ...] = (
    ReasoningLevel.OFF,
    ReasoningLevel.LOW,
    ReasoningLevel.MEDIUM,
    ReasoningLevel.HIGH,
)


@dataclass(frozen=True)
class ReasoningLevelChanged:
    level: ReasoningLevel
    # Which channel actually changed the level - the global hotkey, or a
    # StatusConsoleApi call (Control Center's direct selection, or the
    # touchstrip/compat cycle command). Required, not defaulted: this event
    # has two real trigger paths, and a silent default here is exactly the
    # kind of stale-tag bug a human-run check on 2026-07-13 caught (every
    # caller used to hardcode "HOTKEY", even for a Control Center click).
    source: str


class ReasoningLevelState:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._level = ReasoningLevel.OFF

    @property
    def level(self) -> ReasoningLevel:
        return self._level

    async def set_level(self, level: ReasoningLevel, *, source: str) -> None:
        if level == self._level:
            return
        self._level = level
        await self._bus.publish(
            ReasoningLevelChanged, ReasoningLevelChanged(level=level, source=source)
        )

    async def cycle_level(self, *, source: str) -> None:
        next_index = (CYCLE_ORDER.index(self._level) + 1) % len(CYCLE_ORDER)
        await self.set_level(CYCLE_ORDER[next_index], source=source)


async def run_hotkey_listener(
    state: ReasoningLevelState,
    hotkeys: HotkeySettings,
    provider: HotkeyProvider | None = None,
) -> None:
    """Binds hotkeys.thinking_toggle to a real global hotkey; each press
    calls state.cycle_level(). Runs until cancelled. Hardware-dependent in
    its default form, but provider is injectable so the wiring itself is
    testable without a real keyboard hook.

    Deliberately does not read state.level here to decide what to do: that
    decision must happen inside cycle_level() itself, on the event loop -
    reading state in this callback (which runs on the provider's own
    thread) would race against the event loop's own mutation, same bug
    class task-10's review caught for the mic-sleep hotkey.
    """
    loop = asyncio.get_running_loop()

    def on_cycle() -> None:
        asyncio.run_coroutine_threadsafe(state.cycle_level(source="HOTKEY"), loop)

    await run_hotkey_provider([(hotkeys.thinking_toggle, on_cycle)], provider)
