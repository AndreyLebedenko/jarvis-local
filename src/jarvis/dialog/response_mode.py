"""Three-valued response-mode runtime state (story-v1.9.0, tasks 1-2).

Owns the persistent response mode (`text`/`voice`/`text_voice`) that
selects the turn pipeline's output contract for future turns - the same
"a hotkey/UI change alters a persistent state for the *next* accepted
request, not the currently in-flight one" shape as thinking_mode.py's
ReasoningLevelState. "Persistent" above means persistent for the running
session: since task 3b this module persists nothing, full stop, exactly
like ReasoningLevelState. The seed still comes from build_app()'s
composition root, which reads Settings.response.mode (the Settings form's
restart-to-apply default, written only by write_ui_config from a
Settings-tab Apply) and passes it as `initial_mode`; anything changed
through set_mode()/cycle_mode() - the Ctrl+Alt+O hotkey, the Status-tab
live toggle (ResponseModeChanged's "UI" source since task 3b), or task 4's
voice path - lives only until shutdown.

set_mode()/cycle_mode() publish with no `await` between the read and the
write, same race-avoidance rule as ReasoningLevelState.set_level()/
cycle_level(): the whole read-decide-write must happen synchronously on
the event loop so two rapid triggers (the hotkey, or a hotkey racing a
direct UI selection) can never both observe the same stale mode and
schedule the same transition twice instead of cycling twice.

run_hotkey_listener() mirrors thinking_mode.py's own function directly:
config-driven binding, injectable keyboard module, no direct SoundCuePlayer
dependency (app.py decides what to do with ResponseModeChanged).
"""

import asyncio
import enum
from dataclasses import dataclass

from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings
from jarvis.inputs.hotkeys import HotkeyProvider, run_hotkey_provider


class ResponseMode(enum.Enum):
    TEXT = "text"
    VOICE = "voice"
    TEXT_VOICE = "text_voice"


CYCLE_ORDER: tuple[ResponseMode, ...] = (
    ResponseMode.TEXT,
    ResponseMode.VOICE,
    ResponseMode.TEXT_VOICE,
)


@dataclass(frozen=True)
class ResponseModeChanged:
    mode: ResponseMode
    # Which channel actually changed the mode - required, not defaulted, for
    # the same reason as ReasoningLevelChanged.source: a silent default here
    # is exactly the kind of stale-tag bug a live human check already caught
    # once for that event (every caller hardcoding "HOTKEY"). Construction's
    # config-seeded initial value is never published as a change, so "CONFIG"
    # is not a real source; task 2 introduced "HOTKEY" and "UI", and since
    # task 3b "UI" means the Status-tab live toggle (the Settings drop-down
    # became a restart-to-apply batch field and no longer set_mode()s at
    # all); task 4 introduces "VOICE".
    source: str


class ResponseModeState:
    def __init__(
        self, bus: EventBus, *, initial_mode: ResponseMode = ResponseMode.TEXT
    ) -> None:
        self._bus = bus
        self._mode = initial_mode

    @property
    def mode(self) -> ResponseMode:
        return self._mode

    async def set_mode(self, mode: ResponseMode, *, source: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        await self._bus.publish(
            ResponseModeChanged, ResponseModeChanged(mode=mode, source=source)
        )

    async def cycle_mode(self, *, source: str) -> None:
        next_index = (CYCLE_ORDER.index(self._mode) + 1) % len(CYCLE_ORDER)
        await self.set_mode(CYCLE_ORDER[next_index], source=source)


async def run_hotkey_listener(
    state: ResponseModeState,
    hotkeys: HotkeySettings,
    provider: HotkeyProvider | None = None,
) -> None:
    """Binds hotkeys.response_mode_toggle to a real global hotkey; each
    press calls state.cycle_mode(). Runs until cancelled. Hardware-dependent
    in its default form, but provider is injectable so the wiring itself is
    testable without a real keyboard hook.

    Deliberately does not read state.mode here to decide what to do: that
    decision must happen inside cycle_mode() itself, on the event loop -
    reading state in this callback (which runs on the provider's own
    thread) would race against the event loop's own mutation, same bug
    class thinking_mode.py's own listener guards against."""
    loop = asyncio.get_running_loop()

    def on_cycle() -> None:
        asyncio.run_coroutine_threadsafe(state.cycle_mode(source="HOTKEY"), loop)

    await run_hotkey_provider([(hotkeys.response_mode_toggle, on_cycle)], provider)
