"""Solo session runtime state (owner request, 2026-08-10).

Owns whether the current session is restricted from reading any other
session's data - automatic retrieval, the search_history/read_history
tools, and memory.md/self.md injection at the next session-start moment
(see app.py's Orchestrator and tools/history.py's HistoryToolProvider for
the actual gates; this module only owns the flag and its change event).

Read-side only by design (owner decision, 2026-08-10): turns recorded
while solo is on are journaled normally and remain findable by later
non-solo sessions once solo is turned off - there is no write-side/
permanent isolation and no JournalStore/corpus involvement here.

Mirrors TtsMuteState/VisibilityModeState: a small, single-responsibility
bus-publishing state owner, runtime-only (no config default, never
persisted), freely toggleable at any time.
"""

from dataclasses import dataclass

from jarvis.core.bus import EventBus


@dataclass(frozen=True)
class SoloSessionChanged:
    enabled: bool


class SoloSessionState:
    def __init__(self, bus: EventBus, *, enabled: bool = False) -> None:
        self._bus = bus
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        await self._bus.publish(SoloSessionChanged, SoloSessionChanged(enabled=enabled))
