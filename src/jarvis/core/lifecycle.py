"""Turn and warm-up lifecycle events.

These are the engine-side moments the UI runtime state is derived from
(see jarvis.ui.runtime_state.RuntimeStateTracker). They are published by
the modules that own the moment - warm_up() and the Orchestrator - so no
subscriber has to duplicate busy-guard or completion logic to know what
the engine is doing.
"""

from dataclasses import dataclass
from enum import Enum

# Model-facing current-turn text for a voice turn (not user-facing TTS or
# dialog text), overridable via [prompts].voice_turn_instruction.
#
# Keep it in the assistant's dialog language. This string sits in the `user`
# role, and the system prompt answers in the user's language, so an English
# line here makes the model answer Russian speech in English.
#
# It does not decide whether the model hears the audio - no wording does; a
# request that carries a system prompt or tool declarations loses the audio
# regardless of this text.
VOICE_PLACEHOLDER_TEXT = "Прослушай эту запись и ответь на то, что в ней сказано."


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


class ModelRequestPassKind(Enum):
    PRIMARY = "primary"
    DERIVATIVE = "derivative"


class TextSubmissionReason(Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"
    EMPTY = "empty"
    OVER_LIMIT = "over_limit"


class AttachmentSubmissionReason(Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"
    NO_ACCEPTED_CONTENT = "no_accepted_content"


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
class PersistedFileOutcome:
    """Outcome of persisting one user-marked upload as a session file
    (story-v1.8.1 task 4). ``storage_name``/``bytes`` are set on success and
    ``error`` on failure; the two are mutually exclusive."""

    filename: str
    storage_name: str | None = None
    bytes: int | None = None
    error: str | None = None

    @property
    def persisted(self) -> bool:
        return self.storage_name is not None


@dataclass(frozen=True)
class AttachmentSubmissionResult:
    reason: AttachmentSubmissionReason
    persisted_files: tuple[PersistedFileOutcome, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.reason is AttachmentSubmissionReason.ACCEPTED


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
    """Metadata-only statement that an accepted backend call is beginning.

    speak_streaming (story-v1.9.0 task 3): the playback directive for the
    response this dispatch expects. TtsOutput latches it from the most
    recent ModelRequestStarted and applies it to the ResponseTokens that
    follow - "dispatch precedes streaming" (this event is always awaited
    to completion before the chat task that streams tokens is created) is
    the invariant that latch relies on. Default True means "speak the
    streaming pass", today's behavior for every mode and every caller that
    predates this field.

    pass_kind: PRIMARY for an ordinary single- or first-pass dispatch,
    DERIVATIVE for mode 3's reasoning-off second pass over the exact
    first-pass text. Purely descriptive (logging/events-panel tagging via
    model_request_log_message()) - TtsOutput and the dispatch pipeline
    never branch on it, only on speak_streaming.
    """

    timestamp: float
    inputs: tuple[ModelRequestInput, ...]
    audio_duration_seconds: float | None
    prompt_budget: dict[str, int | bool | str] | None = None
    speak_streaming: bool = True
    pass_kind: ModelRequestPassKind = ModelRequestPassKind.PRIMARY


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
