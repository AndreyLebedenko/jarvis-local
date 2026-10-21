"""What the transcript check stage returns: the transcript to carry forward and
the doubts a later stage may ask the user about. Failures are enums and counts,
never text taken from the transcript, the doubts, or the recording."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DoubtKind(StrEnum):
    FRAGMENT = "fragment"
    REWRITE = "rewrite"
    CHECK_FAILED = "check_failed"


class CheckSource(StrEnum):
    CHECKED = "checked"
    WHISPER_FALLBACK = "whisper_fallback"


class FallbackReason(StrEnum):
    EMPTY_TRANSCRIPT = "empty_transcript"
    CALL_FAILED = "call_failed"
    EMPTY_SAMPLE = "empty_sample"
    UNPARSEABLE_JUDGE = "unparseable_judge"
    INVENTED_ADDRESS = "invented_address"
    ALPHABET_SWITCH = "alphabet_switch"


@dataclass(frozen=True)
class Doubt:
    kind: DoubtKind
    fragment: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CheckedTranscript:
    text: str = field(repr=False)
    doubts: tuple[Doubt, ...]
    source: CheckSource
    would_ask: bool
    fallback_reason: FallbackReason | None = None
