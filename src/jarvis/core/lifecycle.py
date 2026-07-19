"""Turn and warm-up lifecycle events.

These are the engine-side moments the UI runtime state is derived from
(see jarvis.ui.runtime_state.RuntimeStateTracker). They are published by
the modules that own the moment - warm_up() and the Orchestrator - so no
subscriber has to duplicate busy-guard or completion logic to know what
the engine is doing.
"""

from dataclasses import dataclass
from enum import Enum

VOICE_PLACEHOLDER_TEXT = "[голосовое сообщение]"


class TurnSource(Enum):
    VOICE = "voice"
    TEXT = "text"
    TEXT_INPUT = "text_input"
    ATTACHMENT = "attachment"


class ModelRequestInput(Enum):
    AUDIO = "audio"
    SCREENSHOT = "screenshot"
    CLIPBOARD = "clipboard"
    TEXT_INPUT = "text_input"
    ATTACHMENT_IMAGE = "attachment_image"
    ATTACHMENT_AUDIO = "attachment_audio"
    ATTACHMENT_TEXT = "attachment_text"


class TextSubmissionReason(Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"
    EMPTY = "empty"
    OVER_LIMIT = "over_limit"


class NewContextReason(Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"


@dataclass(frozen=True)
class TextSubmissionResult:
    reason: TextSubmissionReason
    max_chars: int

    @property
    def accepted(self) -> bool:
        return self.reason is TextSubmissionReason.ACCEPTED


@dataclass(frozen=True)
class NewContextResult:
    reason: NewContextReason
    session_id: str | None = None
    provenance_text: str | None = None

    @property
    def accepted(self) -> bool:
        return self.reason is NewContextReason.ACCEPTED


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
class ModelRequestStarted:
    """Metadata-only statement that an accepted backend call is beginning."""

    timestamp: float
    inputs: tuple[ModelRequestInput, ...]
    audio_duration_seconds: float | None


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
