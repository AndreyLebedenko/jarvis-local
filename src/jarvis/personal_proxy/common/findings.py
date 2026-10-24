"""What the gate reports. A finding is built only from an enum and integers,
so a matched value has no field to live in."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GateCategory(Enum):
    EMAIL = "email"
    PHONE = "phone"
    PAYMENT_CARD = "payment_card"
    IBAN = "iban"
    DIGIT_RUN = "digit_run"
    API_KEY = "api_key"
    PASSWORD = "password"
    STREET_ADDRESS = "street_address"
    MAPPING_ORIGINAL = "mapping_original"
    TOPIC_TEXT = "topic_text"
    GATE_ERROR = "gate_error"


class GateStage(Enum):
    """Where a GATE_ERROR happened. It names a step, never an exception."""

    INPUT = "input"
    LENGTH = "length"
    EMPTY = "empty"
    NORMALIZATION = "normalization"
    PATTERNS = "patterns"
    MAPPING = "mapping"
    TOPICS = "topics"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Finding:
    category: GateCategory
    message_index: int
    start: int
    end: int
    stage: GateStage | None = None


@dataclass(frozen=True, slots=True)
class GateResult:
    findings: tuple[Finding, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.findings
