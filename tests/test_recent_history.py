from jarvis.app import ConversationHistory
from jarvis.history import (
    ConservativeUtf8TokenEstimator,
    ConversationTurn,
    estimate_history_contribution_tokens,
    select_recent_history,
)


def _turn(role: str, text: str) -> ConversationTurn:
    return ConversationTurn(role=role, text=text)


def _selection_roles_and_texts(selection) -> list[tuple[str, str]]:
    return [(turn.role, turn.text) for turn in selection.turns]


def test_history_turns_returns_a_stable_snapshot():
    history = ConversationHistory()
    history.add("user", "first")
    snapshot = history.turns()

    history.add("assistant", "second")

    assert snapshot == (ConversationTurn(role="user", text="first"),)


def test_select_recent_history_returns_empty_for_empty_input():
    estimator = ConservativeUtf8TokenEstimator()

    selection = select_recent_history(
        (),
        estimator=estimator,
        max_tokens=32,
        minimum_recent_exchanges=1,
    )

    assert selection.turns == ()
    assert selection.estimated_tokens == 0
    assert selection.selected_exchange_count == 0
    assert selection.dropped_exchange_count == 0
    assert selection.truncated is False


def test_select_recent_history_preserves_an_exact_fit():
    estimator = ConservativeUtf8TokenEstimator()
    turns = (
        _turn("user", "remember the relay"),
        _turn("assistant", "The relay is stable."),
        _turn("user", "what changed yesterday?"),
        _turn("assistant", "Only the cooling fan was replaced."),
    )
    exact_budget = estimate_history_contribution_tokens(turns, estimator)

    selection = select_recent_history(
        turns,
        estimator=estimator,
        max_tokens=exact_budget,
        minimum_recent_exchanges=1,
    )

    assert selection.turns == turns
    assert selection.estimated_tokens == exact_budget
    assert selection.selected_exchange_count == 2
    assert selection.dropped_exchange_count == 0
    assert selection.truncated is False


def test_select_recent_history_drops_oldest_exchanges_first():
    estimator = ConservativeUtf8TokenEstimator()
    turns = (
        _turn("user", "alpha request"),
        _turn("assistant", "alpha answer"),
        _turn("user", "beta request"),
        _turn("assistant", "beta answer"),
        _turn("user", "gamma request"),
        _turn("assistant", "gamma answer"),
    )
    newest_two_exchanges = turns[2:]
    budget = estimate_history_contribution_tokens(newest_two_exchanges, estimator)

    selection = select_recent_history(
        turns,
        estimator=estimator,
        max_tokens=budget,
        minimum_recent_exchanges=2,
    )

    assert selection.turns == newest_two_exchanges
    assert selection.selected_exchange_count == 2
    assert selection.dropped_exchange_count == 1
    assert selection.requested_minimum_recent_exchanges == 2
    assert selection.minimum_recent_exchanges_met is True
    assert selection.truncated is True


def test_select_recent_history_keeps_interrupted_note_with_its_exchange():
    estimator = ConservativeUtf8TokenEstimator()
    interrupted_note = "Пользователь прервал этот ответ до того, как он был закончен."
    turns = (
        _turn("user", "answer the diagnostics question"),
        _turn("assistant", "The first probable cause is"),
        _turn("system", interrupted_note),
    )
    exact_budget = estimate_history_contribution_tokens(turns, estimator)

    selection = select_recent_history(
        turns,
        estimator=estimator,
        max_tokens=exact_budget,
        minimum_recent_exchanges=1,
    )

    assert _selection_roles_and_texts(selection) == [
        ("user", "answer the diagnostics question"),
        ("assistant", "The first probable cause is"),
        ("system", interrupted_note),
    ]
    assert selection.selected_exchange_count == 1


def test_select_recent_history_blank_context_clears_the_candidate_tail():
    estimator = ConservativeUtf8TokenEstimator()
    turns = (
        _turn("user", "old context"),
        _turn("assistant", "old answer"),
    )

    selection = select_recent_history(
        turns,
        estimator=estimator,
        max_tokens=999,
        minimum_recent_exchanges=1,
        blank_context=True,
    )

    assert selection.turns == ()
    assert selection.blank_context_cleared is True
    assert selection.minimum_recent_exchanges_met is False
    assert selection.truncated is False


def test_select_recent_history_returns_empty_when_the_newest_exchange_cannot_fit():
    estimator = ConservativeUtf8TokenEstimator()
    turns = (
        _turn("user", "a very long diagnostic question that will not fit"),
        _turn("assistant", "an equally long answer that still will not fit"),
    )

    selection = select_recent_history(
        turns,
        estimator=estimator,
        max_tokens=1,
        minimum_recent_exchanges=1,
    )

    assert selection.turns == ()
    assert selection.selected_exchange_count == 0
    assert selection.dropped_exchange_count == 1
    assert selection.truncated is True
    assert selection.minimum_recent_exchanges_met is False


def test_select_recent_history_keeps_provenance_only_with_first_exchange():
    estimator = ConservativeUtf8TokenEstimator()
    turns = (
        _turn("system", "Continued from 2026-08-01T12:00:00+01:00."),
        _turn("user", "remember the relay"),
        _turn("assistant", "The relay is stable."),
        _turn("user", "what changed yesterday?"),
        _turn("assistant", "Only the cooling fan was replaced."),
    )
    second_exchange_only = turns[3:]
    budget = estimate_history_contribution_tokens(second_exchange_only, estimator)

    selection = select_recent_history(
        turns,
        estimator=estimator,
        max_tokens=budget,
        minimum_recent_exchanges=1,
    )

    assert selection.turns == second_exchange_only
    assert all(turn.role != "system" for turn in selection.turns)
