from __future__ import annotations

import pytest

from jarvis.core.lifecycle import VOICE_PLACEHOLDER_TEXT
from jarvis.journal.events import JournalEvent
from jarvis.journal.fork import (
    ForkSeedOversizeTurnError,
    ForkSeedTurn,
    build_fork_seed,
)
from jarvis.journal.store import JournalReplay


def test_fork_seed_keeps_full_session_when_budget_is_large() -> None:
    replay = _replay(
        _event(role="user", text="привет"),
        _event(role="assistant", source="assistant", text="слушаю"),
    )

    result = build_fork_seed(replay, budget_chars=100)

    assert result.turns == (
        ForkSeedTurn(role="user", text="привет"),
        ForkSeedTurn(role="assistant", text="слушаю"),
    )
    assert result.drop_report.dropped_turns == 0
    assert not result.drop_report.truncated


def test_fork_seed_drops_oldest_turns_to_fit_budget() -> None:
    replay = _replay(
        _event(role="user", text="old"),
        _event(role="assistant", source="assistant", text="middle"),
        _event(role="user", text="new"),
    )

    result = build_fork_seed(replay, budget_chars=9)

    assert result.turns == (
        ForkSeedTurn(role="assistant", text="middle"),
        ForkSeedTurn(role="user", text="new"),
    )
    assert result.drop_report.dropped_turns == 1
    assert result.drop_report.truncated


def test_fork_seed_never_fills_budget_by_cutting_a_hole_in_the_tail() -> None:
    replay = _replay(
        _event(role="user", text="old"),
        _event(role="assistant", source="assistant", text="middle"),
        _event(role="user", text="newer"),
    )

    result = build_fork_seed(replay, budget_chars=8)

    assert result.turns == (ForkSeedTurn(role="user", text="newer"),)
    assert result.drop_report.dropped_turns == 2
    assert result.drop_report.truncated


def test_fork_seed_rejects_single_turn_over_budget() -> None:
    replay = _replay(_event(role="user", text="too long"))

    with pytest.raises(ForkSeedOversizeTurnError) as exc_info:
        build_fork_seed(replay, budget_chars=3)

    assert exc_info.value.turn_chars == len("too long")
    assert exc_info.value.budget_chars == 3


def test_fork_seed_rejects_only_when_the_newest_turn_is_over_budget() -> None:
    replay = _replay(
        _event(role="user", text="ancient oversized"),
        _event(role="assistant", source="assistant", text="new"),
    )

    result = build_fork_seed(replay, budget_chars=3)

    assert result.turns == (ForkSeedTurn(role="assistant", text="new"),)
    assert result.drop_report.dropped_turns == 1


def test_fork_seed_uses_voice_placeholder_without_transcript() -> None:
    replay = _replay(_event(role="user", source="voice", text="", media=("u.wav",)))

    result = build_fork_seed(replay, budget_chars=100)

    assert result.turns == (ForkSeedTurn(role="user", text=VOICE_PLACEHOLDER_TEXT),)


def test_fork_seed_prefers_existing_voice_transcript() -> None:
    replay = _replay(
        _event(
            role="user",
            source="voice",
            text=VOICE_PLACEHOLDER_TEXT,
            transcript="записанная расшифровка",
        )
    )

    result = build_fork_seed(replay, budget_chars=100)

    assert result.turns == (ForkSeedTurn(role="user", text="записанная расшифровка"),)


def test_fork_seed_skips_events_without_model_facing_text() -> None:
    replay = _replay(
        _event(role="assistant", source="assistant", text=""),
        _event(role="user", source="dock", text="текст"),
    )

    result = build_fork_seed(replay, budget_chars=100)

    assert result.turns == (ForkSeedTurn(role="user", text="текст"),)
    assert result.drop_report.skipped_events == 1
    assert result.drop_report.excluded_events == 0


def test_fork_seed_skips_blank_context_provenance_events() -> None:
    replay = _replay(
        _event(
            role="system",
            source="context",
            text="Новый пустой контекст создан пользователем.",
        ),
        _event(role="user", source="dock", text="real turn"),
    )

    result = build_fork_seed(replay, budget_chars=100)

    assert result.turns == (ForkSeedTurn(role="user", text="real turn"),)
    assert result.drop_report.skipped_events == 0
    assert result.drop_report.excluded_events == 1


def test_fork_seed_keeps_fork_provenance_as_part_of_the_seed_chain() -> None:
    replay = _replay(
        _event(role="system", source="fork", text="continued from earlier"),
        _event(role="user", source="dock", text="real turn"),
    )

    result = build_fork_seed(replay, budget_chars=100)

    assert result.turns == (
        ForkSeedTurn(role="system", text="continued from earlier"),
        ForkSeedTurn(role="user", text="real turn"),
    )


def test_fork_seed_is_deterministic() -> None:
    replay = _replay(
        _event(role="user", text="a"),
        _event(role="assistant", source="assistant", text="b"),
        _event(role="user", text="c"),
    )

    first = build_fork_seed(replay, budget_chars=2)
    second = build_fork_seed(replay, budget_chars=2)

    assert first == second


def _replay(*events: JournalEvent) -> JournalReplay:
    return JournalReplay(events=list(events), corrupt_lines=0)


def _event(
    *,
    role: str,
    text: str,
    source: str = "dock",
    media: tuple[str, ...] = (),
    transcript: str | None = None,
) -> JournalEvent:
    return JournalEvent(
        session_id="20260719-100000-ab12",
        timestamp="2026-07-19T10:00:00+01:00",
        source=source,
        role=role,
        text=text,
        media=media,
        transcript=transcript,
    )
