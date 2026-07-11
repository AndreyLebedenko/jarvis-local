"""Turn and warm-up lifecycle events.

These are the engine-side moments the UI runtime state is derived from
(see jarvis.ui.runtime_state.RuntimeStateTracker). They are published by
the modules that own the moment - warm_up() and the Orchestrator - so no
subscriber has to duplicate busy-guard or completion logic to know what
the engine is doing.
"""

from dataclasses import dataclass
from enum import Enum


class TurnSource(Enum):
    VOICE = "voice"
    TEXT = "text"


@dataclass(frozen=True)
class WarmupStarted:
    pass


@dataclass(frozen=True)
class WarmupCompleted:
    succeeded: bool


@dataclass(frozen=True)
class TurnAccepted:
    """A user turn passed the busy guard and is being processed."""

    source: TurnSource


@dataclass(frozen=True)
class BackendRequestFailed:
    """A turn's backend request raised; the turn was abandoned. The next
    ResponseComplete is the recovery signal."""

    pass


@dataclass(frozen=True)
class TurnCompleted:
    """The turn is fully over: history recorded, speech finished, mic
    resumed. Published after the post-turn cooldown, so LISTENING is not
    announced while the assistant is still audibly speaking."""

    pass
