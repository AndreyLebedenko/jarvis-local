"""System visibility mode runtime state (task-ui-05).

Owns whether the Status Console UI is in `Open` or `Hidden` mode - see
story-status-console-ui.md's Key Decisions: this is a *system visibility*
axis (how much the UI shows), independent of `DataLocality` (where
inference runs). Human decision recorded in task-ui-05's card and
tasks/task-ui-privacy-and-touchstrip-requirements.md: in v1, `Hidden` only
changes what the Status Console UI itself displays (labels, module chip
detail, screen-preview detail) - it does not touch audio_in.py, tts.py, or
Orchestrator in any way. Ordinary voice turns speak normally regardless of
this state, so this module has no bus consumer anywhere in main.py's real
wiring - it is driven entirely from status_console.py's StatusConsoleApi
(the UI's own control), unlike thinking_mode.py/audio_in.py's mic-sleep
state, which both have real hotkeys and real engine consumers.

No hotkey listener here (unlike thinking_mode.py/audio_in.py): task-ui-05's
Scope does not call for one, and the story's Product Boundary only asks
for this as a UI-level control.
"""

from dataclasses import dataclass

from bus import EventBus
from ui_contract import VisibilityMode


@dataclass(frozen=True)
class VisibilityModeChanged:
    mode: VisibilityMode


class VisibilityModeState:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._mode = VisibilityMode.OPEN

    @property
    def mode(self) -> VisibilityMode:
        return self._mode

    async def set_mode(self, mode: VisibilityMode) -> None:
        """A no-op (no publish) if mode is already the current mode - unlike
        thinking_mode.py's toggle(), this is a two-button UI control
        (Open/Hidden), not a binary toggle, so a redundant click on the
        already-active mode is a real, expected input that should not
        produce a misleading "changed" event."""
        if mode == self._mode:
            return
        self._mode = mode
        await self._bus.publish(VisibilityModeChanged, VisibilityModeChanged(mode=mode))
