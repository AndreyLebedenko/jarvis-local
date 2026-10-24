"""The two chat blocks of a request as data: what was heard and decided, and
exactly what went out. Neither shows its text in repr or str."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from jarvis.personal_proxy.check.check_result import CheckedTranscript, Doubt
from jarvis.personal_proxy.common.payload import OutboundPayload


class HeardDecision(StrEnum):
    ASK_CONFIRMATION = "ask_confirmation"
    SEND_WITHOUT_QUESTION = "send_without_question"


@dataclass(frozen=True)
class HeardBlock:
    heard_text: str = field(repr=False)
    doubts: tuple[Doubt, ...] = field(repr=False)
    decision: HeardDecision


@dataclass(frozen=True)
class SentBlock:
    messages: tuple[tuple[str, str], ...] = field(repr=False)
    forced: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(f"{role}: {content}" for role, content in self.messages)


ChatBlock = HeardBlock | SentBlock


def heard_block_of(checked: CheckedTranscript, decision: HeardDecision) -> HeardBlock:
    return HeardBlock(checked.text, checked.doubts, decision)


def sent_block_of(payload: OutboundPayload, *, forced: bool = False) -> SentBlock:
    return SentBlock(
        tuple((message.role, message.content) for message in payload.messages),
        forced,
    )
