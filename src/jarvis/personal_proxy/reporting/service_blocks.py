"""The chat blocks the service posts besides the two of the confirmation
exchange. A notice holds an enum kind and an enum, int, or findings detail,
never text taken from a request; the other blocks hold personal text and hide
it from repr and str."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, StrEnum

from jarvis.personal_proxy.check.check_result import Doubt
from jarvis.personal_proxy.common.findings import Finding
from jarvis.personal_proxy.confirmation.confirmation_blocks import ChatBlock
from jarvis.personal_proxy.restoration.restoration_result import (
    RestorationMethod,
    RestoredSentence,
)
from jarvis.personal_proxy.sanitize.sanitize_result import SanitizeVerdict


class NoticeKind(StrEnum):
    NO_SPEECH = "no_speech"
    BAD_AUDIO = "bad_audio"
    REFUSED = "refused"
    SANITIZE_FAILED = "sanitize_failed"
    NOT_SENT = "not_sent"
    GATE_BLOCKED = "gate_blocked"
    ANSWER_INCOMPLETE = "answer_incomplete"
    SPEECH_FAILED = "speech_failed"
    MICROPHONE_FAILED = "microphone_failed"
    INTERNAL_ERROR = "internal_error"
    BUSY = "busy"
    INTERRUPTED = "interrupted"
    UNKNOWN_COMMAND = "unknown_command"
    EMPTY_COMMAND = "empty_command"


NoticeDetail = Enum | int | tuple[Finding, ...] | None


@dataclass(frozen=True)
class NoticeBlock:
    kind: NoticeKind
    detail: NoticeDetail = None
    reason: str = field(default="", repr=False)
    forceable: bool = False

    def __post_init__(self) -> None:
        if not _is_content_free(self.detail):
            raise TypeError("a notice detail is an enum, an int, or findings")


def _is_content_free(detail: object) -> bool:
    if detail is None or isinstance(detail, Enum | int):
        return True
    if isinstance(detail, tuple):
        return all(isinstance(item, Finding) for item in detail)
    return False


@dataclass(frozen=True)
class AnswerBlock:
    text: str = field(repr=False)
    method: RestorationMethod
    unresolved_placeholders: bool


def answer_block_of(sentence: RestoredSentence) -> AnswerBlock:
    return AnswerBlock(sentence.text, sentence.method, sentence.unresolved_placeholders)


@dataclass(frozen=True)
class DryRunBlock:
    """The whole intermediate state of a request that was not sent. It is shown
    in the chat only: it holds personal values."""

    whisper_text: str | None = field(repr=False)
    checked_text: str = field(repr=False)
    doubts: tuple[Doubt, ...] = field(repr=False)
    would_ask: bool
    sanitized_text: str = field(repr=False)
    mapping: Mapping[str, str] = field(repr=False)
    verdict: SanitizeVerdict
    reason: str = field(repr=False)
    gate_findings: tuple[Finding, ...]
    messages: tuple[tuple[str, str], ...] = field(repr=False)
    forced: bool = False


@dataclass(frozen=True)
class RequestSourceBlock:
    """Reaches the persistence writer only, never the chat: where the heard text
    came from. A typed request has neither the recording nor the engine text."""

    voice_wav: bytes | None = field(repr=False)
    raw_transcript: str | None = field(repr=False)


@dataclass(frozen=True)
class AnswerCompleteBlock:
    """Reaches the persistence writer only, never the chat: the answer ended
    after its last sentence."""


PersistenceBlock = RequestSourceBlock | AnswerCompleteBlock
ServiceBlock = ChatBlock | NoticeBlock | AnswerBlock | DryRunBlock | PersistenceBlock
