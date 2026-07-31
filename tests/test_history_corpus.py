from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jarvis.journal import (
    JournalEvent,
    JournalSearchIndex,
    JournalSessionSummary,
    JournalStore,
)
from jarvis.journal.corpus import (
    CURRENT_HISTORY_CORPUS_SCHEMA_VERSION,
    HistoryCorpusRepository,
    HistoryCorpusSchemaError,
)


def test_rebuild_projects_all_valid_events_with_references_and_json_values(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    first = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        role="user",
        source="voice",
        text="привет",
        media=("audio/request.wav", "images/screen.png"),
        metadata={"numbers": [1, 2.5], "nested": {"flag": True, "none": None}},
    )
    second = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:01+01:00",
        role="assistant",
        source="assistant",
        text="ответ",
        transcript="transcript text",
        metadata={"outcome": "interrupted"},
    )
    third = _event(
        session_id="20260717-090000-cd34",
        timestamp="2026-07-17T09:00:00+01:00",
        role="system",
        source="fork",
        text="continued",
        metadata={"seed": {"dropped_turns": 2}},
    )
    for event in (first, second, third):
        store.append(event)

    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    rows = repository.list_events()
    assert [
        (row.reference.session_id, row.reference.event_position, row.role, row.source)
        for row in rows
    ] == [
        ("20260716-153000-ab12", 0, "user", "voice"),
        ("20260716-153000-ab12", 1, "assistant", "assistant"),
        ("20260717-090000-cd34", 0, "system", "fork"),
    ]
    assert rows[0].text == "привет"
    assert rows[0].media == ("audio/request.wav", "images/screen.png")
    assert rows[0].media_count == 2
    assert rows[0].metadata == {
        "numbers": [1, 2.5],
        "nested": {"flag": True, "none": None},
    }
    assert rows[1].transcript == "transcript text"
    assert rows[2].metadata == {"seed": {"dropped_turns": 2}}


def test_rebuild_is_deterministic(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="stable",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")

    repository.rebuild()
    first_rows = repository.list_events()
    repository.rebuild()

    assert repository.list_events() == first_rows


def test_corrupt_raw_lines_are_counted_by_replay_and_absent_from_corpus(
    tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    store = JournalStore(journal_root)
    session_id = "20260716-153000-ab12"
    first = _event(
        session_id=session_id,
        timestamp="2026-07-16T15:30:00+01:00",
        role="user",
        source="voice",
        text="before corrupt",
    )
    second = _event(
        session_id=session_id,
        timestamp="2026-07-16T15:30:01+01:00",
        role="assistant",
        source="assistant",
        text="after corrupt",
    )
    store.append(first)
    events_path = journal_root / session_id / "events.jsonl"
    before_bytes = events_path.read_bytes()
    with events_path.open("a", encoding="utf-8") as file:
        file.write("{not valid json}\n")
        file.write(second.to_json_line())

    HistoryCorpusRepository(store, tmp_path / "derived").rebuild()

    replay = store.read_session(session_id)
    rows = HistoryCorpusRepository(store, tmp_path / "derived").list_events()
    assert replay.corrupt_lines == 1
    assert [(row.reference.event_position, row.text) for row in rows] == [
        (0, "before corrupt"),
        (1, "after corrupt"),
    ]
    assert events_path.read_bytes().startswith(before_bytes)


def test_failed_rebuild_leaves_prior_valid_corpus_intact(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="voice",
            text="old corpus",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()
    prior_rows = repository.list_events()

    failing_store = _FailingReadStore(tmp_path / "journal")
    failing_repository = HistoryCorpusRepository(failing_store, tmp_path / "derived")

    with pytest.raises(RuntimeError, match="boom"):
        failing_repository.rebuild()

    assert repository.list_events() == prior_rows


def test_rebuild_does_not_mutate_raw_jsonl_or_media_bytes(tmp_path: Path) -> None:
    journal_root = tmp_path / "journal"
    store = JournalStore(journal_root)
    session_id = "20260716-153000-ab12"
    store.append(
        _event(
            session_id=session_id,
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="voice",
            text="with media",
            media=("clip.wav",),
        )
    )
    store.write_media(session_id, "clip.wav", b"RIFF demo")
    events_path = journal_root / session_id / "events.jsonl"
    media_path = journal_root / session_id / "clip.wav"
    before = (events_path.read_bytes(), media_path.read_bytes())

    HistoryCorpusRepository(store, tmp_path / "derived").rebuild()

    assert (events_path.read_bytes(), media_path.read_bytes()) == before


def test_unknown_newer_schema_version_fails_explicitly(tmp_path: Path) -> None:
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )
    repository.db_path.parent.mkdir(parents=True)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "CREATE TABLE history_corpus_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO history_corpus_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(CURRENT_HISTORY_CORPUS_SCHEMA_VERSION + 1)),
        )

    with pytest.raises(HistoryCorpusSchemaError, match="newer"):
        repository.list_events()
    with pytest.raises(HistoryCorpusSchemaError, match="newer"):
        repository.rebuild()


def test_rebuild_leaves_legacy_search_index_db_untouched(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="normalized relay row",
        )
    )
    derived_root = tmp_path / "derived"
    legacy_index = JournalSearchIndex(store, derived_root)
    legacy_index.rebuild()
    legacy_index_path = derived_root / "index.db"
    legacy_size_before = legacy_index_path.stat().st_size

    repository = HistoryCorpusRepository(store, derived_root)
    repository.rebuild()

    assert legacy_index_path.exists()
    assert legacy_index_path.stat().st_size == legacy_size_before
    assert [hit.snippet for hit in legacy_index.search("relay")] == [
        "normalized [relay] row"
    ]

    with sqlite3.connect(repository.db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type IN ('table', 'virtual table')
                """
            )
        }
    assert "journal_search_events" not in tables
    assert "history_corpus_events" in tables
    assert not any(table.endswith("_fts") for table in tables)
    assert [row.text for row in repository.list_events()] == ["normalized relay row"]


class _FailingReadStore(JournalStore):
    def list_sessions(self) -> list[JournalSessionSummary]:
        return [
            JournalSessionSummary(
                session_id="20260716-153000-ab12",
                first_timestamp="2026-07-16T15:30:00+01:00",
                last_timestamp="2026-07-16T15:30:00+01:00",
            )
        ]

    def read_session(self, session_id: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


def _event(
    *,
    session_id: str,
    timestamp: str,
    role: str,
    source: str,
    text: str,
    media: tuple[str, ...] = (),
    transcript: str | None = None,
    metadata: dict | None = None,
) -> JournalEvent:
    return JournalEvent(
        session_id=session_id,
        timestamp=timestamp,
        source=source,
        role=role,
        text=text,
        media=media,
        transcript=transcript,
        metadata=metadata or {},
    )
