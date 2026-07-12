"""Status Console contract: the shapes the UI consumes.

Per story-status-console-ui.md's Key Decisions, the UI consumes engine
state through explicit events/snapshots and must not parse console output
or infer state from unrelated module internals. This module defines those
shapes only - pure data, no bus wiring, no GUI framework dependency, so it
can be imported by any future Status Console implementation (desktop shell,
touchstrip surface) regardless of which framework task-ui-02 ends up
choosing.

See task-ui-01-state-and-event-contract.md for the full contract
documentation, including the mapping from these shapes to existing bus
events and the list of events that do not exist yet.

Reasoning-token isolation (PROJECT.md's thinking-mode rule) extends here:
message.thinking must never reach a SystemEvent.message any more than it
reaches ResponseToken - future publishers of SystemEvent must not log
reasoning text, only operational statements about what a module is doing.
"""

import enum
from dataclasses import dataclass

from jarvis.core.lifecycle import ModelRequestInput


class RuntimeState(enum.Enum):
    """The six states the status orb can be in. WARMING is a runtime
    activation/warmup state (tasks/backlog/activation-warmup.md), not a
    privacy or data-locality indicator - see VisibilityMode/DataLocality
    below for those, which are independent axes."""

    IDLE = "idle"
    WARMING = "warming"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


class ModuleId(enum.Enum):
    """The module chips required by story-status-console-ui.md's Product
    Boundary. BACKEND covers the Ollama/model pair (shown as one chip in
    the mock-up); MEMORY covers conversation history/context, not a
    separate storage service - v1.0 has no such service."""

    BACKEND = "backend"
    MICROPHONE = "microphone"
    TTS = "tts"
    MEMORY = "memory"
    VISION = "vision"


class HealthStatus(enum.Enum):
    """UNAVAILABLE is distinct from ERROR: a module that is off by
    design (e.g. vision/screen before any capture this session) is not
    the same condition as a module that failed."""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ModuleHealth:
    module: ModuleId
    status: HealthStatus
    detail: str = ""


@dataclass(frozen=True)
class ModelRequestItem:
    kind: ModelRequestInput
    audio_duration_seconds: float | None = None


@dataclass(frozen=True)
class ModelRequestSummary:
    timestamp: float
    items: tuple[ModelRequestItem, ...]


class EventLevel(enum.Enum):
    """Matches the four-way legend in .planning/UI/mock-ups/
    jarvis_status_console_v1.html: info / active / warn / error."""

    INFO = "info"
    ACTIVE = "active"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class SystemEvent:
    """timestamp is a time.time() float; the UI formats it for display,
    this module does not decide the display format. correlation_id is
    optional and lets the UI group events from the same turn/request
    once a caller has one to offer - nothing in v1.0 generates one yet."""

    timestamp: float
    source: str
    level: EventLevel
    message: str
    correlation_id: str | None = None


class VisibilityMode(enum.Enum):
    """System visibility mode (tasks/task-ui-privacy-and-touchstrip-
    requirements.md): how much Jarvis exposes itself outward. Independent
    of DataLocality below - Hidden does not change where inference runs,
    and Local/External does not change whether TTS/screen previews are
    shown."""

    OPEN = "open"
    HIDDEN = "hidden"


class DataLocality(enum.Enum):
    """Where the active backend runs. v1.0 only ever reports LOCAL - see
    PROJECT.md's Architecture v1.0 (Ollama is the only supported v1.0
    backend); EXTERNAL is defined now so the enum does not need to change
    shape the day a non-local provider is added, per story's Product
    Boundary explicitly excluding cloud provider switching from v1 scope."""

    LOCAL = "local"
    EXTERNAL = "external"
