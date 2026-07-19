from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis.core.lifecycle import VOICE_PLACEHOLDER_TEXT
from jarvis.journal.events import JournalEvent
from jarvis.journal.store import JournalReplay


@dataclass(frozen=True)
class ForkSeedTurn:
    role: str
    text: str


@dataclass(frozen=True)
class ForkSeedDropReport:
    dropped_turns: int
    skipped_events: int
    truncated: bool


@dataclass(frozen=True)
class ForkSeedResult:
    turns: tuple[ForkSeedTurn, ...]
    drop_report: ForkSeedDropReport


class ForkSessionReason(Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"
    OVERSIZE_TURN = "oversize_turn"


@dataclass(frozen=True)
class ForkSessionResult:
    reason: ForkSessionReason
    new_session_id: str | None = None
    drop_report: ForkSeedDropReport | None = None
    provenance_text: str | None = None
    oversize_turn_chars: int | None = None
    max_chars: int | None = None

    @property
    def accepted(self) -> bool:
        return self.reason is ForkSessionReason.ACCEPTED


class ForkSeedOversizeTurnError(ValueError):
    def __init__(self, turn_chars: int, budget_chars: int) -> None:
        super().__init__("a single journal turn exceeds the fork seed character budget")
        self.turn_chars = turn_chars
        self.budget_chars = budget_chars


def build_fork_seed(replay: JournalReplay, budget_chars: int) -> ForkSeedResult:
    if budget_chars < 0:
        raise ValueError("budget_chars must not be negative")

    seedable_turns: list[ForkSeedTurn] = []
    skipped_events = 0
    for event in replay.events:
        turn = _seed_turn(event)
        if turn is None:
            skipped_events += 1
        else:
            seedable_turns.append(turn)

    for turn in seedable_turns:
        turn_chars = len(turn.text)
        if turn_chars > budget_chars:
            raise ForkSeedOversizeTurnError(turn_chars, budget_chars)

    selected_reversed: list[ForkSeedTurn] = []
    selected_chars = 0
    dropped_turns = 0
    for turn in reversed(seedable_turns):
        turn_chars = len(turn.text)
        if selected_chars + turn_chars > budget_chars:
            dropped_turns += 1
            continue
        selected_reversed.append(turn)
        selected_chars += turn_chars

    selected = tuple(reversed(selected_reversed))
    return ForkSeedResult(
        turns=selected,
        drop_report=ForkSeedDropReport(
            dropped_turns=dropped_turns,
            skipped_events=skipped_events,
            truncated=dropped_turns > 0,
        ),
    )


def _seed_turn(event: JournalEvent) -> ForkSeedTurn | None:
    text = _model_facing_text(event)
    if text == "":
        return None
    return ForkSeedTurn(role=event.role, text=text)


def _model_facing_text(event: JournalEvent) -> str:
    if event.role == "user" and event.source == "voice":
        if event.transcript is not None and event.transcript != "":
            return event.transcript
        if event.text != "":
            return event.text
        return VOICE_PLACEHOLDER_TEXT
    return event.text
