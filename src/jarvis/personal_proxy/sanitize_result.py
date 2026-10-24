"""What the sanitize stage returns: a validated result, or a typed failure.
Nothing taken from the transcript, the topics, or the model's output appears
in a failure, a repr, or an exception."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

MAX_REASON_LENGTH = 200
NO_SPEECH_REASON = "no speech"


class SanitizeVerdict(StrEnum):
    SEND = "send"
    REFUSE = "refuse"


class SanitizeFailureClass(StrEnum):
    BACKEND_FAILED = "backend_failed"
    TRUNCATED = "truncated"
    EMPTY = "empty"
    NO_JSON = "no_json"
    EXTRA_PROSE = "extra_prose"
    MISSING_FIELD = "missing_field"
    WRONG_TYPE = "wrong_type"
    BAD_VERDICT = "bad_verdict"
    EMPTY_SANITIZED_TEXT = "empty_sanitized_text"
    BAD_PLACEHOLDER = "bad_placeholder"
    EMPTY_MAPPING_VALUE = "empty_mapping_value"
    UNEXPECTED_REFUSAL = "unexpected_refusal"


@dataclass(frozen=True)
class SanitizeFailure:
    failure: SanitizeFailureClass


@dataclass(frozen=True)
class SanitizeResult:
    verdict: SanitizeVerdict
    reason: str = field(repr=False)
    sanitized_text: str = field(repr=False)
    mapping: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping", MappingProxyType(dict(self.mapping)))
