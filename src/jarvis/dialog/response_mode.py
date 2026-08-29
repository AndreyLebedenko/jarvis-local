"""Three-valued response-mode runtime state (story-v1.9.0, task 1).

Owns the persistent response mode (`text`/`voice`/`text_voice`) that
selects the turn pipeline's output contract for future turns - the same
"a hotkey/UI change alters a persistent state for the *next* accepted
request, not the currently in-flight one" shape as thinking_mode.py's
ReasoningLevelState.

Persistence delta from that precedent: ReasoningLevelState always starts
at `off` and is never persisted across restart. ResponseModeState is
seeded from `[response].mode` instead - build_app()'s composition root
reads Settings.response.mode and passes it as `initial_mode` - and, from
task 2 onward, the UI writes new selections back to config.ui.toml. This
module owns only the runtime state and its config-seeded construction;
the hotkey listener (mirroring thinking_mode.py's run_hotkey_listener)
and the UI write-back both land in task 2.

set_mode()/cycle_mode() publish with no `await` between the read and the
write, same race-avoidance rule as ReasoningLevelState.set_level()/
cycle_level(): the whole read-decide-write must happen synchronously on
the event loop so two rapid triggers (e.g. a hotkey, once task 2 wires
one) can never both observe the same stale mode and schedule the same
transition twice instead of cycling twice.
"""

import enum
from dataclasses import dataclass

from jarvis.core.bus import EventBus


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
    # is not a real source; task 2 introduces "HOTKEY" and "UI", task 4
    # introduces "VOICE".
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
