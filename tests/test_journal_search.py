from __future__ import annotations

from pathlib import Path

from jarvis.journal import JournalEvent, JournalSearchIndex, JournalStore


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
    (tmp_path / "index.db").unlink()
    index.rebuild()

    assert index.search("telemetry") == first_results
    assert [(hit.session_id, hit.event_position) for hit in first_results] == [
        ("20260717-090000-cd34", 0)
    ]


def test_search_indexes_assistant_text_only(tmp_path: Path) -> None:
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

    assert index.search("private-user-token") == []
    assert [hit.snippet for hit in index.search("assistant")] == [
        "public [assistant] answer"
    ]


def test_search_before_rebuild_is_read_only_and_returns_no_hits(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    index = JournalSearchIndex(store, tmp_path)

    assert index.search("anything") == []
    assert not (tmp_path / "index.db").exists()


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


def _event(
    *,
    session_id: str,
    timestamp: str,
    role: str,
    source: str,
    text: str,
) -> JournalEvent:
    return JournalEvent(
        session_id=session_id,
        timestamp=timestamp,
        source=source,
        role=role,
        text=text,
        media=[],
        transcript=None,
    )
