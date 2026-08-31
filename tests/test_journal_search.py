from __future__ import annotations

from pathlib import Path

from jarvis.journal import (
    HistoryCorpusRepository,
    HistorySearchOrder,
    HistorySearchRequest,
    HistorySearchStatus,
    HistorySessionReadStatus,
    JournalEvent,
    JournalSearchIndex,
    JournalSessionSummary,
    JournalStore,
)


def test_rebuild_from_store_can_recreate_disposable_index(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="The orbital relay is stable.",
        )
    )
    store.append(
        _event(
            session_id="20260717-090000-cd34",
            timestamp="2026-07-17T09:00:00+01:00",
            role="assistant",
            source="assistant",
            text="The reactor telemetry is nominal.",
        )
    )
    index = JournalSearchIndex(store, tmp_path)

    index.rebuild()
    first_results = index.search("telemetry")
    (tmp_path / "history_corpus.db").unlink()
    index.rebuild()

    assert index.search("telemetry") == first_results
    assert [(hit.session_id, hit.event_position) for hit in first_results] == [
        ("20260717-090000-cd34", 0)
    ]


def test_search_indexes_user_and_assistant_text(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    session_id = "20260716-153000-ab12"
    store.append(
        _event(
            session_id=session_id,
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="text",
            text="private-user-token",
        )
    )
    store.append(
        _event(
            session_id=session_id,
            timestamp="2026-07-16T15:30:01+01:00",
            role="assistant",
            source="assistant",
            text="public assistant answer",
        )
    )

    index = JournalSearchIndex(store, tmp_path)
    index.rebuild()

    assert [hit.snippet for hit in index.search("private-user-token")] == [
        "[private]-[user]-[token]"
    ]
    assert [hit.snippet for hit in index.search("assistant")] == [
        "public [assistant] answer"
    ]


def test_history_search_indexes_raw_user_and_assistant_text(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    user_ref = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="text",
            text="private-user-token",
        )
    )
    assistant_ref = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:01+01:00",
            role="assistant",
            source="assistant",
            text="public assistant answer",
        )
    )
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:02+01:00",
            role="system",
            source="context",
            text="system-token",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    user_result = repository.search(HistorySearchRequest(query="private-user"))
    assistant_result = repository.search(HistorySearchRequest(query="assistant"))
    system_result = repository.search(HistorySearchRequest(query="system-token"))

    assert user_result.status is HistorySearchStatus.ACCEPTED
    assert [hit.reference for hit in user_result.hits] == [user_ref]
    assert user_result.hits[0].snippet == "[private]-[user]-token"
    assert [hit.reference for hit in assistant_result.hits] == [assistant_ref]
    assert system_result.hits == ()


def test_search_before_rebuild_is_read_only_and_returns_no_hits(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    index = JournalSearchIndex(store, tmp_path)

    assert index.search("anything") == []
    assert not (tmp_path / "index.db").exists()


def test_history_search_before_rebuild_is_unavailable_and_read_only(
    tmp_path: Path,
) -> None:
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )

    result = repository.search(HistorySearchRequest(query="anything"))

    assert result.status is HistorySearchStatus.UNAVAILABLE
    assert result.hits == ()
    assert not repository.db_path.exists()


def test_search_date_filter_is_inclusive_and_date_to_covers_whole_day(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    session_id = "20260716-235900-ab12"
    _append_assistant(
        store,
        session_id=session_id,
        timestamp="2026-07-16T23:59:59+01:00",
        text="cross midnight before",
    )
    _append_assistant(
        store,
        session_id=session_id,
        timestamp="2026-07-17T00:00:00+01:00",
        text="cross midnight boundary",
    )
    _append_assistant(
        store,
        session_id="20260718-010000-cd34",
        timestamp="2026-07-18T01:00:00+01:00",
        text="cross midnight after",
    )
    index = JournalSearchIndex(store, tmp_path)
    index.rebuild()

    hits = index.search(
        "cross",
        date_from="2026-07-16T23:59:59+01:00",
        date_to="2026-07-17",
    )

    assert [(hit.session_id, hit.timestamp) for hit in hits] == [
        (session_id, "2026-07-16T23:59:59+01:00"),
        (session_id, "2026-07-17T00:00:00+01:00"),
    ]


def test_history_search_filters_compose_by_role_source_session_and_time(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    kept = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="text",
            text="shared filter target",
        )
    )
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T16:00:00+01:00",
            role="assistant",
            source="assistant",
            text="shared filter target",
        )
    )
    store.append(
        _event(
            session_id="20260717-153000-cd34",
            timestamp="2026-07-17T15:30:00+01:00",
            role="user",
            source="voice",
            text="shared filter target",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    result = repository.search(
        HistorySearchRequest(
            query="shared",
            date_from="2026-07-16",
            date_to="2026-07-16",
            session_ids=("20260716-153000-ab12",),
            roles=("user",),
            sources=("text",),
            order=HistorySearchOrder.CHRONOLOGICAL,
        )
    )

    assert result.status is HistorySearchStatus.ACCEPTED
    assert [hit.reference for hit in result.hits] == [kept]


def test_date_only_mode_returns_matching_assistant_events(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    _append_assistant(
        store,
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        text="first day answer",
    )
    _append_assistant(
        store,
        session_id="20260717-153000-cd34",
        timestamp="2026-07-17T15:30:00+01:00",
        text="second day answer",
    )
    index = JournalSearchIndex(store, tmp_path)
    index.rebuild()

    hits = index.search("", date_from="2026-07-17", date_to="2026-07-17")

    assert [(hit.session_id, hit.event_position, hit.snippet) for hit in hits] == [
        ("20260717-153000-cd34", 0, "second day answer")
    ]


def test_cyrillic_exact_and_prefix_queries_match_assistant_answers(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    _append_assistant(
        store,
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        text="Система запомнила русский ответ.",
    )
    index = JournalSearchIndex(store, tmp_path)
    index.rebuild()

    assert [hit.session_id for hit in index.search("русский")] == [
        "20260716-153000-ab12"
    ]
    assert [hit.session_id for hit in index.search("рус")] == ["20260716-153000-ab12"]
    assert [hit.session_id for hit in index.search("р")] == ["20260716-153000-ab12"]


def test_history_search_cyrillic_exact_and_prefix_queries_match_raw_text(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    reference = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="text",
            text="Система запомнила русский ответ.",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    assert [
        hit.reference for hit in repository.search(HistorySearchRequest("русский")).hits
    ] == [reference]
    assert [
        hit.reference for hit in repository.search(HistorySearchRequest("рус")).hits
    ] == [reference]
    assert [
        hit.reference for hit in repository.search(HistorySearchRequest("р")).hits
    ] == [reference]


def test_history_search_order_modes_are_deterministic(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    older = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="relay",
        )
    )
    newer = store.append(
        _event(
            session_id="20260717-153000-cd34",
            timestamp="2026-07-17T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="relay relay relay",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    relevance = repository.search(
        HistorySearchRequest("relay", order=HistorySearchOrder.RELEVANCE)
    )
    chronological = repository.search(
        HistorySearchRequest("relay", order=HistorySearchOrder.CHRONOLOGICAL)
    )

    assert [hit.reference for hit in relevance.hits] == [newer, older]
    assert [hit.reference for hit in chronological.hits] == [older, newer]
    assert [hit.order_index for hit in relevance.hits] == [0, 1]
    assert relevance.hits[0].score < relevance.hits[1].score


def test_history_search_hits_read_back_to_the_same_event(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    reference = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="read back target",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    search = repository.search(HistorySearchRequest("target"))
    read = repository.read_event(search.hits[0].reference)

    assert [hit.reference for hit in search.hits] == [reference]
    assert read.event is not None
    assert read.event.text == "read back target"


def test_history_search_enforces_strict_result_limit(tmp_path: Path) -> None:
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )

    too_low = repository.search(HistorySearchRequest("anything", limit=0))
    too_high = repository.search(HistorySearchRequest("anything", limit=501))

    assert too_low.status is HistorySearchStatus.INVALID_LIMIT
    assert too_high.status is HistorySearchStatus.TOO_MANY_RESULTS


def test_update_session_replaces_existing_session_rows(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    session_id = "20260716-153000-ab12"
    _append_assistant(
        store,
        session_id=session_id,
        timestamp="2026-07-16T15:30:00+01:00",
        text="old answer",
    )
    index = JournalSearchIndex(store, tmp_path)
    index.rebuild()
    _append_assistant(
        store,
        session_id=session_id,
        timestamp="2026-07-16T15:31:00+01:00",
        text="new answer",
    )

    index.update_session(session_id)

    assert [hit.snippet for hit in index.search("answer")] == [
        "old [answer]",
        "new [answer]",
    ]


def test_update_session_replays_only_the_requested_session(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    session_id = "20260716-153000-ab12"
    other_session_id = "20260717-153000-cd34"
    _append_assistant(
        store,
        session_id=session_id,
        timestamp="2026-07-16T15:30:00+01:00",
        text="old answer",
    )
    _append_assistant(
        store,
        session_id=other_session_id,
        timestamp="2026-07-17T15:30:00+01:00",
        text="other answer",
    )
    JournalSearchIndex(store, tmp_path).rebuild()
    _append_assistant(
        store,
        session_id=session_id,
        timestamp="2026-07-16T15:31:00+01:00",
        text="new answer",
    )
    no_list_store = _NoListJournalStore(tmp_path)
    index = JournalSearchIndex(no_list_store, tmp_path)

    index.update_session(session_id)

    assert [hit.snippet for hit in index.search("answer")] == [
        "old [answer]",
        "new [answer]",
        "other [answer]",
    ]


def test_delete_session_removes_only_that_sessions_projection(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    deleted_session = "20260716-153000-ab12"
    kept_session = "20260717-153000-cd34"
    _append_assistant(
        store,
        session_id=deleted_session,
        timestamp="2026-07-16T15:30:00+01:00",
        text="shared answer deleted",
    )
    _append_assistant(
        store,
        session_id=kept_session,
        timestamp="2026-07-17T15:30:00+01:00",
        text="shared answer kept",
    )
    index = JournalSearchIndex(store, tmp_path)
    index.rebuild()

    index.delete_session(deleted_session)

    assert [(hit.session_id, hit.snippet) for hit in index.search("shared")] == [
        (kept_session, "[shared] answer kept")
    ]
    repository = HistoryCorpusRepository(store, tmp_path)
    assert (
        repository.read_session(deleted_session).status
        is HistorySessionReadStatus.UNKNOWN_SESSION
    )
    assert (
        repository.read_session(kept_session).status is HistorySessionReadStatus.FOUND
    )


def _append_assistant(
    store: JournalStore,
    *,
    session_id: str,
    timestamp: str,
    text: str,
) -> None:
    store.append(
        _event(
            session_id=session_id,
            timestamp=timestamp,
            role="assistant",
            source="assistant",
            text=text,
        )
    )


# --- Locator surfacing through the Journal search index (story-v1.9.1 task 4)


def _locator_fixture(tmp_path: Path) -> tuple[JournalSearchIndex, JournalStore]:
    store = JournalStore(tmp_path / "journal")
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="Канонический ответ.",
        )
    )
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:05+01:00",
            role="assistant",
            source="assistant",
            text="Реле перегрелось после обеда.",
            metadata={"spoken_derivative": "напоминаю, реле перегрелось из-за пыли"},
        )
    )
    index = JournalSearchIndex(store, tmp_path / "derived")
    index.rebuild()
    return index, store


def test_journal_search_returns_canonical_hits_without_locator_matches(
    tmp_path: Path,
) -> None:
    index, _ = _locator_fixture(tmp_path)

    hits = index.search("перегрелось из-за пыли")

    # The derivative-only phrase must not surface as an ordinary canonical
    # hit; the locator path is a separate query.
    assert hits == []


def test_journal_locator_search_returns_labeled_hits_with_canonical_text(
    tmp_path: Path,
) -> None:
    index, _ = _locator_fixture(tmp_path)

    hits = index.search_locator("перегрелось из-за пыли")

    assert len(hits) == 1
    hit = hits[0]
    assert (hit.session_id, hit.event_position) == ("20260716-153000-ab12", 1)
    assert hit.kind == "locator"
    assert hit.canonical_text == "Реле перегрелось после обеда."
    # Recognition snippet must come from the derivative, only it carries
    # these words; snippet markup brackets the matched tokens.
    assert "пыли" in hit.snippet
    assert hit.snippet != hit.canonical_text


def test_canonical_journal_search_hit_is_labeled_canonical(tmp_path: Path) -> None:
    index, _ = _locator_fixture(tmp_path)

    hits = index.search("Канонический")

    assert len(hits) == 1
    assert hits[0].kind == "canonical"


async def test_search_history_returns_no_locator_content_for_derivative_phrase(
    tmp_path: Path,
) -> None:
    # Model-facing decision default (task 4): UI-only. search_history must
    # return neither locator items nor derivative text, and must not count
    # any locator match among its lexical/semantic hits.
    index, store = _locator_fixture(tmp_path)
    from jarvis.journal import HistoryRetrievalResult, HistoryRetrievalStatus
    from jarvis.tools.history import SEARCH_HISTORY_TOOL_NAME, HistoryToolProvider

    provider = HistoryToolProvider(
        repository=index.repository,
        retrieval_service=_StaticRetrievalService(
            HistoryRetrievalResult(HistoryRetrievalStatus.ACCEPTED)
        ),
    )

    result = await provider.call_tool(
        SEARCH_HISTORY_TOOL_NAME, {"query": "из-за пыли", "limit": 5}
    )

    assert result.is_error is False
    payload = result.structured_content
    assert payload["results"] == []
    assert payload["returned_count"] == 0
    assert payload["lexical_count"] == 0
    assert payload["semantic_count"] == 0
    # The derivative text and the canonical answer never reach the payload
    # results (the echoed query string is not content).
    results_text = str(payload["results"])
    assert "напоминаю" not in results_text
    assert "Реле перегрелось после обеда." not in results_text


class _StaticRetrievalService:
    def __init__(self, result: object) -> None:
        self._result = result

    def retrieve(self, request: object) -> object:
        return self._result


def _event(
    *,
    session_id: str,
    timestamp: str,
    role: str,
    source: str,
    text: str,
    metadata: dict | None = None,
) -> JournalEvent:
    return JournalEvent(
        session_id=session_id,
        timestamp=timestamp,
        source=source,
        role=role,
        text=text,
        media=[],
        transcript=None,
        metadata=metadata or {},
    )


class _NoListJournalStore(JournalStore):
    def list_sessions(self) -> list[JournalSessionSummary]:
        raise RuntimeError("update_session must not list every journal session")
