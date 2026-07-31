from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jarvis.journal import (
    JournalEvent,
    JournalEventRef,
    JournalSearchIndex,
    JournalSessionSummary,
    JournalStore,
)
from jarvis.journal.corpus import (
    CURRENT_HISTORY_CORPUS_SCHEMA_VERSION,
    HISTORY_READ_MAX_BATCH_RANGES,
    HISTORY_READ_MAX_EVENTS_PER_RANGE,
    HISTORY_READ_MAX_TOTAL_EVENTS,
    HistoryBatchReadStatus,
    HistoryCorpusRepository,
    HistoryCorpusSchemaError,
    HistoryEventRange,
    HistoryEventRangeStatus,
    HistoryEventReadStatus,
    HistoryEventRefsReadStatus,
    HistorySessionReadStatus,
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


def test_read_event_returns_exact_provenance_and_payload(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    reference = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="voice",
            text="привет",
            media=("audio/request.wav",),
            metadata={"language": "ru"},
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    result = repository.read_event(reference)

    assert result.status is HistoryEventReadStatus.FOUND
    assert result.event is not None
    assert result.event.reference == reference
    assert result.event.timestamp == "2026-07-16T15:30:00+01:00"
    assert result.event.role == "user"
    assert result.event.source == "voice"
    assert result.event.text == "привет"
    assert result.event.media == ("audio/request.wav",)
    assert result.event.media_count == 1
    assert result.event.metadata == {"language": "ru"}


def test_read_event_reports_unknown_reference(tmp_path: Path) -> None:
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )

    result = repository.read_event(JournalEventRef("20260716-153000-ab12", 0))

    assert result.status is HistoryEventReadStatus.UNKNOWN_REFERENCE
    assert result.event is None


def test_read_events_preserves_explicit_reference_order_and_reports_missing(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    first = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="voice",
            text="first",
        )
    )
    second = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:01+01:00",
            role="assistant",
            source="assistant",
            text="second",
        )
    )
    missing = JournalEventRef("20260716-153000-ab12", 9)
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    result = repository.read_events((second, missing, first))

    assert result.status is HistoryEventRefsReadStatus.ACCEPTED
    assert [event.reference for event in result.events] == [second, first]
    assert result.missing_references == (missing,)


def test_read_events_enforces_total_limit_before_query(tmp_path: Path) -> None:
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )
    reference = JournalEventRef("20260716-153000-ab12", 0)

    result = repository.read_events((reference,) * (HISTORY_READ_MAX_TOTAL_EVENTS + 1))

    assert result.status is HistoryEventRefsReadStatus.TOO_MANY_REFERENCES
    assert result.events == ()
    assert result.max_references == HISTORY_READ_MAX_TOTAL_EVENTS


def test_read_range_returns_inclusive_session_order(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    _append_sequence(store, "20260716-153000-ab12", ("zero", "one", "two", "three"))
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    result = repository.read_range(
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 1),
            JournalEventRef("20260716-153000-ab12", 3),
        )
    )

    assert result.status is HistoryEventRangeStatus.FOUND
    assert [
        (event.reference.event_position, event.text) for event in result.events
    ] == [
        (1, "one"),
        (2, "two"),
        (3, "three"),
    ]


def test_read_range_reports_invalid_unknown_and_over_limit_outcomes(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    _append_sequence(store, "20260716-153000-ab12", ("zero", "one"))
    _append_sequence(store, "20260717-090000-cd34", ("other",))
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    cross_session = repository.read_range(
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 0),
            JournalEventRef("20260717-090000-cd34", 0),
        )
    )
    reversed_range = repository.read_range(
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 1),
            JournalEventRef("20260716-153000-ab12", 0),
        )
    )
    unknown_start = repository.read_range(
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 7),
            JournalEventRef("20260716-153000-ab12", 8),
        )
    )
    over_limit = repository.read_range(
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 0),
            JournalEventRef("20260716-153000-ab12", HISTORY_READ_MAX_EVENTS_PER_RANGE),
        )
    )

    assert cross_session.status is HistoryEventRangeStatus.CROSS_SESSION
    assert reversed_range.status is HistoryEventRangeStatus.REVERSED_RANGE
    assert unknown_start.status is HistoryEventRangeStatus.UNKNOWN_START_REFERENCE
    assert unknown_start.missing_reference == JournalEventRef("20260716-153000-ab12", 7)
    assert over_limit.status is HistoryEventRangeStatus.TOO_MANY_EVENTS
    assert over_limit.max_events == HISTORY_READ_MAX_EVENTS_PER_RANGE


def test_read_surrounding_returns_bounded_context_around_reference(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    _append_sequence(
        store,
        "20260716-153000-ab12",
        ("zero", "one", "two", "three", "four"),
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    result = repository.read_surrounding(
        JournalEventRef("20260716-153000-ab12", 2), before=1, after=2
    )

    assert result.status is HistoryEventRangeStatus.FOUND
    assert [
        (event.reference.event_position, event.text) for event in result.events
    ] == [
        (1, "one"),
        (2, "two"),
        (3, "three"),
        (4, "four"),
    ]


def test_read_surrounding_reports_negative_unknown_and_over_limit(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    reference = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="voice",
            text="only",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    negative = repository.read_surrounding(reference, before=-1, after=0)
    unknown = repository.read_surrounding(
        JournalEventRef("20260716-153000-ab12", 5), before=1, after=1
    )
    clipped_to_session = repository.read_surrounding(
        reference, before=HISTORY_READ_MAX_EVENTS_PER_RANGE, after=0
    )

    assert negative.status is HistoryEventRangeStatus.NEGATIVE_CONTEXT_LIMIT
    assert unknown.status is HistoryEventRangeStatus.UNKNOWN_REFERENCE
    assert clipped_to_session.status is HistoryEventRangeStatus.FOUND
    assert [event.reference for event in clipped_to_session.events] == [reference]


def test_read_surrounding_enforces_limit_after_clipping_to_session(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    references = _append_sequence(
        store,
        "20260716-153000-ab12",
        tuple(
            str(position) for position in range(HISTORY_READ_MAX_EVENTS_PER_RANGE + 1)
        ),
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    over_limit = repository.read_surrounding(
        references[-1], before=HISTORY_READ_MAX_EVENTS_PER_RANGE, after=0
    )

    assert over_limit.status is HistoryEventRangeStatus.TOO_MANY_EVENTS
    assert over_limit.requested_count == HISTORY_READ_MAX_EVENTS_PER_RANGE + 1


def test_read_session_metadata_reports_found_and_unknown(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    _append_sequence(store, "20260716-153000-ab12", ("zero", "one", "two"))
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    found = repository.read_session("20260716-153000-ab12")
    unknown = repository.read_session("20260717-090000-cd34")

    assert found.status is HistorySessionReadStatus.FOUND
    assert found.session is not None
    assert found.session.session_id == "20260716-153000-ab12"
    assert found.session.first_event_position == 0
    assert found.session.last_event_position == 2
    assert found.session.event_count == 3
    assert found.session.first_timestamp == "2026-07-16T15:30:00+01:00"
    assert found.session.last_timestamp == "2026-07-16T15:30:02+01:00"
    assert unknown.status is HistorySessionReadStatus.UNKNOWN_SESSION
    assert unknown.session is None


def test_read_ranges_returns_ordered_ranges_and_per_range_outcomes(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    _append_sequence(store, "20260716-153000-ab12", ("zero", "one", "two"))
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()

    result = repository.read_ranges(
        (
            HistoryEventRange(
                JournalEventRef("20260716-153000-ab12", 0),
                JournalEventRef("20260716-153000-ab12", 1),
            ),
            HistoryEventRange(
                JournalEventRef("20260716-153000-ab12", 2),
                JournalEventRef("20260716-153000-ab12", 9),
            ),
        )
    )

    assert result.status is HistoryBatchReadStatus.ACCEPTED
    assert [range_read.status for range_read in result.ranges] == [
        HistoryEventRangeStatus.FOUND,
        HistoryEventRangeStatus.UNKNOWN_END_REFERENCE,
    ]
    assert [event.text for event in result.ranges[0].events] == ["zero", "one"]
    assert result.total_events == 2


def test_read_ranges_enforces_batch_count_and_total_result_caps(
    tmp_path: Path,
) -> None:
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )
    unit_range = HistoryEventRange(
        JournalEventRef("20260716-153000-ab12", 0),
        JournalEventRef("20260716-153000-ab12", 0),
    )
    too_many_ranges = (unit_range,) * (HISTORY_READ_MAX_BATCH_RANGES + 1)
    too_many_events = (
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 0),
            JournalEventRef("20260716-153000-ab12", HISTORY_READ_MAX_TOTAL_EVENTS),
        ),
    )

    range_count_result = repository.read_ranges(too_many_ranges)
    total_count_result = repository.read_ranges(too_many_events)

    assert range_count_result.status is HistoryBatchReadStatus.TOO_MANY_RANGES
    assert range_count_result.ranges == ()
    assert range_count_result.max_ranges == HISTORY_READ_MAX_BATCH_RANGES
    assert total_count_result.status is HistoryBatchReadStatus.TOO_MANY_EVENTS
    assert total_count_result.ranges == ()
    assert total_count_result.max_events == HISTORY_READ_MAX_TOTAL_EVENTS


def test_read_ranges_total_cap_cannot_be_bypassed_by_splitting_ranges(
    tmp_path: Path,
) -> None:
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )
    ranges = (
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 0),
            JournalEventRef("20260716-153000-ab12", 199),
        ),
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 200),
            JournalEventRef("20260716-153000-ab12", 399),
        ),
        HistoryEventRange(
            JournalEventRef("20260716-153000-ab12", 400),
            JournalEventRef("20260716-153000-ab12", 599),
        ),
    )

    result = repository.read_ranges(ranges)

    assert result.status is HistoryBatchReadStatus.TOO_MANY_EVENTS
    assert result.ranges == ()
    assert result.requested_events == 600
    assert result.max_events == HISTORY_READ_MAX_TOTAL_EVENTS


def test_read_methods_use_corpus_without_replaying_raw_journal(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    reference = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="voice",
            text="stored in corpus",
        )
    )
    derived_root = tmp_path / "derived"
    HistoryCorpusRepository(store, derived_root).rebuild()
    repository = HistoryCorpusRepository(
        _FailingReadStore(tmp_path / "journal"), derived_root
    )

    result = repository.read_event(reference)

    assert result.status is HistoryEventReadStatus.FOUND
    assert result.event is not None
    assert result.event.text == "stored in corpus"


def test_reads_do_not_modify_corpus_or_raw_journal(tmp_path: Path) -> None:
    journal_root = tmp_path / "journal"
    store = JournalStore(journal_root)
    reference = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="user",
            source="voice",
            text="stable",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()
    events_path = journal_root / reference.session_id / "events.jsonl"
    before = (events_path.read_bytes(), repository.db_path.read_bytes())

    repository.read_event(reference)
    repository.read_events((reference,))
    repository.read_range(HistoryEventRange(reference, reference))
    repository.read_surrounding(reference, before=0, after=0)
    repository.read_session(reference.session_id)
    repository.read_ranges((HistoryEventRange(reference, reference),))

    assert (events_path.read_bytes(), repository.db_path.read_bytes()) == before


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


def _append_sequence(
    store: JournalStore, session_id: str, texts: tuple[str, ...]
) -> tuple[JournalEventRef, ...]:
    references = []
    start = datetime.fromisoformat("2026-07-16T15:30:00+01:00")
    for position, text in enumerate(texts):
        timestamp = start + timedelta(seconds=position)
        references.append(
            store.append(
                _event(
                    session_id=session_id,
                    timestamp=timestamp.isoformat(),
                    role="user" if position % 2 == 0 else "assistant",
                    source="voice" if position % 2 == 0 else "assistant",
                    text=text,
                )
            )
        )
    return tuple(references)
