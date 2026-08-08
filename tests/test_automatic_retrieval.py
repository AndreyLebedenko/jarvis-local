from __future__ import annotations

from jarvis.history import (
    AutomaticRetrievalSelectionLimits,
    ConservativeUtf8TokenEstimator,
    ConversationTurn,
    RecentHistoryExchange,
    RecentHistorySelection,
    build_automatic_retrieval_request,
    select_automatic_retrieval_passages,
    to_history_retrieval_query,
)
from jarvis.history.working_context import (
    RetrievedHistoryPassage,
    estimate_working_context_tokens,
    format_retrieved_history_passages,
)
from jarvis.journal import (
    AnnotationCandidateIdentity,
    HistoryRetrievalCandidate,
    HistoryRetrievalCandidateKind,
    HistoryRetrievalSourceMode,
    JournalEventRef,
)


def _turn(role: str, text: str) -> ConversationTurn:
    return ConversationTurn(role=role, text=text)


def _recent_history(*turns: ConversationTurn) -> RecentHistorySelection:
    if not turns:
        return RecentHistorySelection(
            prefix_turns=(),
            exchanges=(),
            estimated_tokens=0,
            max_tokens=256,
            total_exchange_count=0,
            selected_exchange_count=0,
            dropped_exchange_count=0,
            requested_minimum_recent_exchanges=1,
            minimum_recent_exchanges_met=False,
            truncated=False,
            blank_context_cleared=False,
        )
    exchange = RecentHistoryExchange(turns=turns)
    return RecentHistorySelection(
        prefix_turns=(),
        exchanges=(exchange,),
        estimated_tokens=0,
        max_tokens=256,
        total_exchange_count=1,
        selected_exchange_count=1,
        dropped_exchange_count=0,
        requested_minimum_recent_exchanges=1,
        minimum_recent_exchanges_met=True,
        truncated=False,
        blank_context_cleared=False,
    )


def _candidate(
    index: int,
    text: str,
    *,
    source_mode: HistoryRetrievalSourceMode,
    combined_rank: int,
    semantic_score: float | None = None,
    lexical_score: float | None = None,
    lexical_rank: int | None = None,
    role: str = "assistant",
    source: str = "text",
) -> HistoryRetrievalCandidate:
    return HistoryRetrievalCandidate(
        reference=JournalEventRef("20260801-100000-ab12", index),
        text=text,
        timestamp="2026-08-01T10:00:00+01:00",
        role=role,
        source=source,
        source_mode=source_mode,
        combined_rank=combined_rank,
        semantic_score=semantic_score,
        lexical_score=lexical_score,
        lexical_rank=lexical_rank,
    )


def test_build_automatic_retrieval_request_joins_current_and_recent_texts() -> None:
    recent_history = _recent_history(
        _turn("user", "помни про насос"),
        _turn("assistant", "Насос перегрелся после обеда."),
        _turn("system", "не включать в запрос"),
    )

    request = build_automatic_retrieval_request(
        "Как это связано с прошлым сбоем?",
        recent_history,
        session_ids=("20260801-100000-ab12",),
        date_from="2026-08-01",
        roles=("user", "assistant"),
        sources=("text",),
    )

    assert request.query_text == (
        "Как это связано с прошлым сбоем?\n\n"
        "помни про насос\n\n"
        "Насос перегрелся после обеда."
    )
    assert request.session_ids == ("20260801-100000-ab12",)
    assert request.date_from == "2026-08-01"
    assert request.roles == ("user", "assistant")
    assert request.sources == ("text",)


def test_to_history_retrieval_query_preserves_filters_and_limit() -> None:
    request = build_automatic_retrieval_request(
        "Что поменялось?",
        _recent_history(_turn("user", "старый контекст")),
        session_ids=("20260801-100000-ab12", "20260801-100100-fd01"),
        date_from="2026-08-01",
        date_to="2026-08-02",
        roles=("user",),
        sources=("text",),
    )

    query = to_history_retrieval_query(request, limit=7)

    assert query.query == "Что поменялось?\n\nстарый контекст"
    assert query.limit == 7
    assert query.session_ids == ("20260801-100000-ab12", "20260801-100100-fd01")
    assert query.date_from == "2026-08-01"
    assert query.date_to == "2026-08-02"
    assert query.roles == ("user",)
    assert query.sources == ("text",)


def test_select_automatic_retrieval_prefers_semantic_paraphrase_and_skips_overlap():
    estimator = ConservativeUtf8TokenEstimator()
    recent_history = _recent_history(
        _turn("user", "Система уже жаловалась на реле."),
        _turn("assistant", "Реле щёлкает, но не замыкается."),
    )
    request = build_automatic_retrieval_request("Как починить реле?", recent_history)
    limits = AutomaticRetrievalSelectionLimits(
        candidate_limit=4,
        passage_limit=2,
        minimum_relevance=0.5,
        token_budget=512,
    )
    candidates = (
        _candidate(
            0,
            "Реле щёлкает, но не замыкается.",
            source_mode=HistoryRetrievalSourceMode.BOTH,
            combined_rank=1,
            semantic_score=0.91,
            lexical_rank=1,
        ),
        _candidate(
            1,
            "После обеда насос перегрелся.",
            source_mode=HistoryRetrievalSourceMode.SEMANTIC,
            combined_rank=2,
            semantic_score=0.82,
        ),
        _candidate(
            2,
            "Реле щёлкает, но не замыкается.",
            source_mode=HistoryRetrievalSourceMode.LEXICAL,
            combined_rank=3,
            lexical_rank=1,
        ),
    )

    selection = select_automatic_retrieval_passages(
        request,
        candidates,
        limits,
        estimator=estimator,
    )

    assert selection.selected_passage_count == 1
    assert selection.selected_passages[0].text == "После обеда насос перегрелся."
    assert selection.selected_passages[0].truncated is False
    assert selection.skipped_duplicate_count == 2
    assert selection.skipped_weak_count == 0
    assert selection.estimated_tokens == estimate_working_context_tokens(
        [
            {
                "role": "system",
                "content": format_retrieved_history_passages(
                    selection.selected_passages
                ),
            }
        ],
        estimator=estimator,
    )


def test_select_automatic_retrieval_does_not_match_short_recent_word_inside_word() -> (
    None
):
    estimator = ConservativeUtf8TokenEstimator()
    recent_history = _recent_history(_turn("user", "да"))
    request = build_automatic_retrieval_request("Что произошло?", recent_history)
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "Это правда.",
                source_mode=HistoryRetrievalSourceMode.SEMANTIC,
                combined_rank=1,
                semantic_score=0.9,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=1,
            passage_limit=1,
            minimum_relevance=0.5,
            token_budget=256,
        ),
        estimator=estimator,
    )

    assert [passage.text for passage in selection.selected_passages] == ["Это правда."]
    assert selection.skipped_duplicate_count == 0


def test_select_automatic_retrieval_keeps_candidate_with_recent_phrase() -> None:
    estimator = ConservativeUtf8TokenEstimator()
    recent_history = _recent_history(_turn("assistant", "спасибо"))
    request = build_automatic_retrieval_request(
        "Что сказано про реле?",
        recent_history,
    )
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "Реле не сработало, спасибо за отчёт.",
                source_mode=HistoryRetrievalSourceMode.SEMANTIC,
                combined_rank=1,
                semantic_score=0.9,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=1,
            passage_limit=1,
            minimum_relevance=0.5,
            token_budget=512,
        ),
        estimator=estimator,
    )

    assert [passage.text for passage in selection.selected_passages] == [
        "Реле не сработало, спасибо за отчёт."
    ]
    assert selection.skipped_duplicate_count == 0


def test_select_automatic_retrieval_accepts_exact_identifier_fallback() -> None:
    estimator = ConservativeUtf8TokenEstimator()
    request = build_automatic_retrieval_request("A-2481", _recent_history())
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "В журнале указан A-2481 как номер заказа.",
                source_mode=HistoryRetrievalSourceMode.LEXICAL,
                combined_rank=1,
                lexical_rank=1,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=1,
            passage_limit=1,
            minimum_relevance=0.5,
            token_budget=1024,
        ),
        estimator=estimator,
    )

    assert [passage.text for passage in selection.selected_passages] == [
        "В журнале указан A-2481 как номер заказа."
    ]
    assert selection.skipped_weak_count == 0


def test_select_automatic_retrieval_accepts_prefix_fallback() -> None:
    estimator = ConservativeUtf8TokenEstimator()
    request = build_automatic_retrieval_request("велосип", _recent_history())
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "Велосипед сломан после дождя.",
                source_mode=HistoryRetrievalSourceMode.LEXICAL,
                combined_rank=1,
                lexical_rank=1,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=1,
            passage_limit=1,
            minimum_relevance=0.5,
            token_budget=1024,
        ),
        estimator=estimator,
    )

    assert [passage.text for passage in selection.selected_passages] == [
        "Велосипед сломан после дождя."
    ]


def test_select_automatic_retrieval_accepts_lexical_only_candidates() -> None:
    estimator = ConservativeUtf8TokenEstimator()
    request = build_automatic_retrieval_request(
        "Что изменилось?",
        _recent_history(),
    )
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "Сначала заменили вентилятор.",
                source_mode=HistoryRetrievalSourceMode.LEXICAL,
                combined_rank=1,
                lexical_rank=1,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=1,
            passage_limit=1,
            minimum_relevance=0.5,
            token_budget=1024,
        ),
        estimator=estimator,
    )

    assert [passage.text for passage in selection.selected_passages] == [
        "Сначала заменили вентилятор."
    ]
    assert selection.selected_passages[0].source == "text"


def test_select_automatic_retrieval_skips_low_relevance_matches() -> None:
    estimator = ConservativeUtf8TokenEstimator()
    request = build_automatic_retrieval_request(
        "Почему не сработало реле?",
        _recent_history(),
    )
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "Случайная заметка, не связанная с реле.",
                source_mode=HistoryRetrievalSourceMode.SEMANTIC,
                combined_rank=1,
                semantic_score=0.12,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=1,
            passage_limit=1,
            minimum_relevance=0.5,
            token_budget=128,
        ),
        estimator=estimator,
    )

    assert selection.selected_passages == ()
    assert selection.skipped_weak_count == 1


def test_select_automatic_retrieval_keeps_order_for_tied_scores() -> None:
    estimator = ConservativeUtf8TokenEstimator()
    request = build_automatic_retrieval_request(
        "Что изменилось?",
        _recent_history(),
    )
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "Сначала заменили вентилятор.",
                source_mode=HistoryRetrievalSourceMode.SEMANTIC,
                combined_rank=1,
                semantic_score=0.8,
            ),
            _candidate(
                1,
                "Потом заменили реле.",
                source_mode=HistoryRetrievalSourceMode.SEMANTIC,
                combined_rank=2,
                semantic_score=0.8,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=2,
            passage_limit=2,
            minimum_relevance=0.5,
            token_budget=1024,
        ),
        estimator=estimator,
    )

    assert [passage.text for passage in selection.selected_passages] == [
        "Сначала заменили вентилятор.",
        "Потом заменили реле.",
    ]


def test_select_automatic_retrieval_returns_empty_for_blank_input() -> None:
    estimator = ConservativeUtf8TokenEstimator()
    request = build_automatic_retrieval_request("", _recent_history())
    selection = select_automatic_retrieval_passages(
        request,
        (
            _candidate(
                0,
                "Старая заметка.",
                source_mode=HistoryRetrievalSourceMode.LEXICAL,
                combined_rank=1,
                lexical_rank=1,
            ),
        ),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=1,
            passage_limit=1,
            minimum_relevance=0.5,
            token_budget=64,
        ),
        estimator=estimator,
    )

    assert selection.selected_passages == ()
    assert selection.estimated_tokens == 0
    assert selection.inspected_candidate_count == 0


def test_select_automatic_retrieval_skips_low_relevance_and_stays_within_budget() -> (
    None
):
    estimator = ConservativeUtf8TokenEstimator()
    request = build_automatic_retrieval_request(
        "Почему не сработало реле?",
        _recent_history(),
    )
    short_candidate = _candidate(
        0,
        "Реле не сработало из-за перегрева.",
        source_mode=HistoryRetrievalSourceMode.SEMANTIC,
        combined_rank=2,
        semantic_score=0.88,
    )
    long_text = " ".join(["Подробное объяснение"] * 80)
    long_candidate = _candidate(
        1,
        long_text,
        source_mode=HistoryRetrievalSourceMode.SEMANTIC,
        combined_rank=1,
        semantic_score=0.93,
    )
    short_budget = estimate_working_context_tokens(
        [
            {
                "role": "system",
                "content": format_retrieved_history_passages(
                    (
                        RetrievedHistoryPassage(
                            reference=short_candidate.reference,
                            role=short_candidate.role,
                            source=short_candidate.source,
                            timestamp=short_candidate.timestamp,
                            text=short_candidate.text,
                            truncated=False,
                        ),
                    )
                ),
            }
        ],
        estimator=estimator,
    )

    selection = select_automatic_retrieval_passages(
        request,
        (long_candidate, short_candidate),
        AutomaticRetrievalSelectionLimits(
            candidate_limit=2,
            passage_limit=2,
            minimum_relevance=0.5,
            token_budget=short_budget,
        ),
        estimator=estimator,
    )

    assert [passage.text for passage in selection.selected_passages] == [
        "Реле не сработало из-за перегрева."
    ]
    assert selection.skipped_capacity_count == 1


def test_automatic_retrieval_passage_marks_transcript_source():
    candidate = HistoryRetrievalCandidate(
        reference=JournalEventRef("20260801-100000-ab12", 0),
        text="секретный код альфа",
        timestamp="2026-08-01T10:00:00+01:00",
        role="user",
        source="voice",
        source_mode=HistoryRetrievalSourceMode.LEXICAL,
        combined_rank=1,
        lexical_score=1.0,
        lexical_rank=1,
        text_is_transcript=True,
    )
    request = build_automatic_retrieval_request(
        "код альфа", _recent_history(), roles=("user",), sources=("voice",)
    )

    selection = select_automatic_retrieval_passages(
        request,
        (candidate,),
        AutomaticRetrievalSelectionLimits(),
        estimator=ConservativeUtf8TokenEstimator(),
    )

    assert selection.selected_passage_count == 1
    passage = selection.selected_passages[0]
    # The transcript flag survives selection and reaches the model-facing
    # working-context payload, so the transcript is framed as a transcript and
    # not as the user's own verbatim words.
    assert passage.text_is_transcript is True
    formatted = format_retrieved_history_passages(selection.selected_passages)
    assert '"text_is_transcript":true' in formatted


def test_automatic_retrieval_carries_annotation_kind_into_passage():
    candidate = HistoryRetrievalCandidate(
        reference=None,
        text="Пользователь предпочитает краткие ответы.",
        timestamp="2026-08-01T10:00:00+01:00",
        role="annotation",
        source="generated",
        source_mode=HistoryRetrievalSourceMode.SEMANTIC,
        combined_rank=1,
        kind=HistoryRetrievalCandidateKind.ANNOTATION,
        annotation=AnnotationCandidateIdentity(
            annotation_id="ann-1",
            session_id="20260801-100000-ab12",
            source="generated",
        ),
        semantic_score=0.9,
    )
    request = build_automatic_retrieval_request("краткие ответы", _recent_history())

    selection = select_automatic_retrieval_passages(
        request,
        (candidate,),
        AutomaticRetrievalSelectionLimits(),
        estimator=ConservativeUtf8TokenEstimator(),
    )

    assert selection.selected_passage_count == 1
    passage = selection.selected_passages[0]
    assert passage.kind is HistoryRetrievalCandidateKind.ANNOTATION
    assert passage.reference is None
    assert passage.annotation is not None
    assert passage.annotation.annotation_id == "ann-1"
    formatted = format_retrieved_history_passages(selection.selected_passages)
    assert '"kind":"annotation"' in formatted
    assert '"annotation_id":"ann-1"' in formatted
