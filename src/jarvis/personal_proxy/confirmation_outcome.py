"""How a confirmation exchange can end. Only a confirmation may lead to a send."""

from __future__ import annotations

from enum import StrEnum


class ExchangeOutcome(StrEnum):
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    UNCLEAR = "unclear"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def leads_to_send(self) -> bool:
        return self is ExchangeOutcome.CONFIRMED


class ExchangeState(StrEnum):
    ASKING = "asking"
    AWAITING = "awaiting"
    DONE = "done"


class Delivery(StrEnum):
    """Whether the exchange took an answer offered to it."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class FailureStage(StrEnum):
    """Which stage an exchange failed in; nothing else about the failure."""

    SINK = "sink"
    SPEAKER = "speaker"
    MICROPHONE = "microphone"
    TRANSCRIBER = "transcriber"
    INTERNAL = "internal"
