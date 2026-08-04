from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from jarvis.journal.events import JournalEvent, JournalEventRecord, JournalEventRef
from jarvis.journal.lifecycle import (
    JournalStoreEventReferenceResolver,
    TranscriptHistoryProjection,
)
from jarvis.journal.store import JournalStore
from jarvis.journal.transcript import (
    TRANSCRIPT_MAX_TEXT_LENGTH,
    TranscriptDeleteStatus,
    TranscriptOverlayRepository,
    TranscriptOverlaySchemaError,
    TranscriptReadStatus,
    TranscriptSource,
    TranscriptUpsertStatus,
)


class _FakeReferences:
    """Existence resolver whose known set the test controls explicitly."""

    def __init__(self, known: set[JournalEventRef] | None = None) -> None:
        self._known = known
        self.queried: list[JournalEventRef] = []

    def event_exists(self, reference: JournalEventRef) -> bool:
        self.queried.append(reference)
        if self._known is None:
            return True
        return reference in self._known


def _ref(
    session_id: str = "20260801-120000-ab12", event_position: int = 0
) -> JournalEventRef:
    return JournalEventRef(session_id, event_position)


def _repo(
    tmp_path: Path, references: _FakeReferences | None = None
) -> TranscriptOverlayRepository:
    return TranscriptOverlayRepository(
        tmp_path / "derived", references or _FakeReferences()
    )


class TestUpsertAndRead:
    def test_upsert_creates_new_transcript(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        ref = _ref()
        result = repo.upsert_transcript(ref, "hello world", TranscriptSource.GENERATED)
        assert result.accepted

        read = repo.read_transcript(ref)
        assert read.found
        assert read.overlay is not None
        assert read.overlay.reference == ref
        assert read.overlay.text == "hello world"
        assert read.overlay.source is TranscriptSource.GENERATED
        assert read.overlay.created_at
        assert read.overlay.updated_at

    def test_upsert_updates_existing_transcript(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        ref = _ref()
        repo.upsert_transcript(ref, "first version", TranscriptSource.GENERATED)
        first = repo.read_transcript(ref)
        assert first.overlay is not None

        repo.upsert_transcript(ref, "second version", TranscriptSource.EDITED)
        second = repo.read_transcript(ref)
        assert second.overlay is not None
        assert second.overlay.text == "second version"
        assert second.overlay.source is TranscriptSource.EDITED
        assert second.overlay.created_at == first.overlay.created_at
        assert second.overlay.updated_at >= first.overlay.updated_at

    def test_read_returns_not_found_for_missing_reference(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        read = repo.read_transcript(_ref())
        assert not read.found
        assert read.status is TranscriptReadStatus.NOT_FOUND
        assert read.overlay is None

    def test_read_returns_not_found_when_no_db(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        read = repo.read_transcript(_ref())
        assert read.status is TranscriptReadStatus.NOT_FOUND

    def test_upsert_preserves_created_at_on_update(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        ref = _ref()
        repo.upsert_transcript(ref, "v1", TranscriptSource.RAW)
        first = repo.read_transcript(ref)
        assert first.overlay is not None
        original_created = first.overlay.created_at

        repo.upsert_transcript(ref, "v2", TranscriptSource.EDITED)
        second = repo.read_transcript(ref)
        assert second.overlay is not None
        assert second.overlay.created_at == original_created

    def test_upsert_stores_unicode_text(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        ref = _ref()
        text = "Привет мир! 你好世界"
        repo.upsert_transcript(ref, text, TranscriptSource.GENERATED)
        read = repo.read_transcript(ref)
        assert read.overlay is not None
        assert read.overlay.text == text


class TestValidation:
    def test_rejects_empty_text(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.upsert_transcript(_ref(), "", TranscriptSource.GENERATED)
        assert not result.accepted
        assert result.status is TranscriptUpsertStatus.TEXT_EMPTY

    def test_rejects_over_limit_text(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        text = "x" * (TRANSCRIPT_MAX_TEXT_LENGTH + 1)
        result = repo.upsert_transcript(_ref(), text, TranscriptSource.GENERATED)
        assert not result.accepted
        assert result.status is TranscriptUpsertStatus.TEXT_TOO_LONG

    def test_accepts_text_at_limit(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        text = "x" * TRANSCRIPT_MAX_TEXT_LENGTH
        result = repo.upsert_transcript(_ref(), text, TranscriptSource.GENERATED)
        assert result.accepted

    def test_rejects_unknown_reference(self, tmp_path: Path) -> None:
        references = _FakeReferences(known=set())
        repo = _repo(tmp_path, references)
        ref = _ref()
        result = repo.upsert_transcript(ref, "orphan", TranscriptSource.GENERATED)
        assert not result.accepted
        assert result.status is TranscriptUpsertStatus.UNKNOWN_REFERENCE
        assert references.queried == [ref]

    def test_unknown_reference_persists_nothing(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _FakeReferences(known=set()))
        ref = _ref()
        repo.upsert_transcript(ref, "orphan", TranscriptSource.GENERATED)
        assert not repo.read_transcript(ref).found
        assert repo.count() == 0

    def test_accepts_known_reference(self, tmp_path: Path) -> None:
        ref = _ref()
        repo = _repo(tmp_path, _FakeReferences(known={ref}))
        result = repo.upsert_transcript(ref, "known", TranscriptSource.GENERATED)
        assert result.accepted


class TestDelete:
    def test_delete_existing_transcript(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        ref = _ref()
        repo.upsert_transcript(ref, "text", TranscriptSource.GENERATED)
        result = repo.delete_transcript(ref)
        assert result.status is TranscriptDeleteStatus.DELETED

        read = repo.read_transcript(ref)
        assert not read.found

    def test_delete_nonexistent_returns_not_found(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.delete_transcript(_ref())
        assert result.status is TranscriptDeleteStatus.NOT_FOUND

    def test_delete_nonexistent_no_db_returns_not_found(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.delete_transcript(_ref())
        assert result.status is TranscriptDeleteStatus.NOT_FOUND


class TestSessionDelete:
    def test_session_delete_removes_all_session_transcripts(
        self, tmp_path: Path
    ) -> None:
        repo = _repo(tmp_path)
        sid = "20260801-120000-ab12"
        repo.upsert_transcript(
            JournalEventRef(sid, 0), "t1", TranscriptSource.GENERATED
        )
        repo.upsert_transcript(
            JournalEventRef(sid, 1), "t2", TranscriptSource.GENERATED
        )
        repo.upsert_transcript(
            JournalEventRef("20260802-100000-cd34", 0),
            "other",
            TranscriptSource.GENERATED,
        )

        repo.delete_session(sid)

        assert not repo.read_transcript(JournalEventRef(sid, 0)).found
        assert not repo.read_transcript(JournalEventRef(sid, 1)).found
        assert repo.read_transcript(JournalEventRef("20260802-100000-cd34", 0)).found

    def test_session_delete_no_db_is_noop(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.delete_session("20260801-120000-ab12")

    def test_session_delete_empty_session_is_noop(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        repo.delete_session("20260801-120000-ab12")


class TestReadSessionTranscripts:
    def test_returns_ordered_transcripts(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        sid = "20260801-120000-ab12"
        repo.upsert_transcript(
            JournalEventRef(sid, 2), "third", TranscriptSource.GENERATED
        )
        repo.upsert_transcript(
            JournalEventRef(sid, 0), "first", TranscriptSource.GENERATED
        )
        repo.upsert_transcript(
            JournalEventRef(sid, 1), "second", TranscriptSource.EDITED
        )

        overlays = repo.read_session_transcripts(sid)
        assert len(overlays) == 3
        assert [o.reference.event_position for o in overlays] == [0, 1, 2]
        assert [o.text for o in overlays] == ["first", "second", "third"]

    def test_returns_empty_for_unknown_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert repo.read_session_transcripts("20260801-120000-ab12") == ()

    def test_returns_empty_when_no_db(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert repo.read_session_transcripts("20260801-120000-ab12") == ()


class TestRebuild:
    def test_rebuild_creates_schema(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        assert repo.db_path.exists()
        assert repo.count() == 0

    def test_rebuild_preserves_existing_data(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        ref = _ref()
        repo.upsert_transcript(ref, "keep me", TranscriptSource.GENERATED)
        repo.rebuild()
        read = repo.read_transcript(ref)
        assert read.found
        assert read.overlay is not None
        assert read.overlay.text == "keep me"

    def test_rebuild_idempotent(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        repo.rebuild()
        assert repo.count() == 0


class TestCount:
    def test_count_empty(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        assert repo.count() == 0

    def test_count_after_inserts(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        sid = "20260801-120000-ab12"
        repo.upsert_transcript(JournalEventRef(sid, 0), "a", TranscriptSource.GENERATED)
        repo.upsert_transcript(JournalEventRef(sid, 1), "b", TranscriptSource.GENERATED)
        assert repo.count() == 2

    def test_count_no_db(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert repo.count() == 0


class TestSchemaVersion:
    def test_newer_schema_version_raises(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        with closing(sqlite3.connect(repo.db_path)) as conn, conn:
            conn.execute(
                "UPDATE transcript_overlay_meta SET value = ? WHERE key = ?",
                ("999", "schema_version"),
            )
        with pytest.raises(TranscriptOverlaySchemaError, match="newer schema"):
            repo.read_transcript(_ref())

    def test_invalid_schema_version_raises(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        with closing(sqlite3.connect(repo.db_path)) as conn, conn:
            conn.execute(
                "UPDATE transcript_overlay_meta SET value = ? WHERE key = ?",
                ("not_a_number", "schema_version"),
            )
        with pytest.raises(TranscriptOverlaySchemaError, match="Invalid"):
            repo.read_transcript(_ref())


class TestProjectionLifecycle:
    def test_projection_rebuild_creates_schema(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        projection = TranscriptHistoryProjection(repo)
        assert projection.name == "transcript"
        projection.rebuild()
        assert repo.db_path.exists()

    def test_projection_rebuild_preserves_data(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        ref = _ref()
        repo.upsert_transcript(ref, "preserved", TranscriptSource.GENERATED)
        projection = TranscriptHistoryProjection(repo)
        projection.rebuild()
        assert repo.read_transcript(ref).found

    def test_projection_project_event_is_noop(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        projection = TranscriptHistoryProjection(repo)
        projection.rebuild()
        record = JournalEventRecord(
            _ref(),
            JournalEvent(
                session_id="20260801-120000-ab12",
                timestamp="2026-08-01T12:00:00+01:00",
                source="voice",
                role="user",
                text="hello",
                media=(),
                transcript=None,
            ),
        )
        projection.project_event(record)
        assert repo.count() == 0

    def test_projection_delete_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        sid = "20260801-120000-ab12"
        repo.upsert_transcript(
            JournalEventRef(sid, 0), "text", TranscriptSource.GENERATED
        )
        projection = TranscriptHistoryProjection(repo)
        projection.delete_session_projection(sid)
        assert not repo.read_transcript(JournalEventRef(sid, 0)).found


class TestRawJournalUnchanged:
    def test_upsert_does_not_create_or_modify_jsonl(self, tmp_path: Path) -> None:
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        sentinel = journal_dir / "events.jsonl"
        sentinel.write_text("original content", encoding="utf-8")
        original_bytes = sentinel.read_bytes()

        repo = _repo(tmp_path)
        repo.upsert_transcript(_ref(), "transcript text", TranscriptSource.GENERATED)

        assert sentinel.read_bytes() == original_bytes


class TestJournalStoreReferenceResolver:
    def test_known_raw_event_is_accepted_orphan_rejected(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        store.append(
            JournalEvent(
                session_id="20260801-120000-ab12",
                timestamp="2026-08-01T12:00:00+01:00",
                source="voice",
                role="user",
                text="привет",
                media=(),
                transcript=None,
            )
        )
        repo = TranscriptOverlayRepository(
            tmp_path / "derived", JournalStoreEventReferenceResolver(store)
        )

        known = JournalEventRef("20260801-120000-ab12", 0)
        orphan_position = JournalEventRef("20260801-120000-ab12", 5)
        orphan_session = JournalEventRef("20260901-090000-ffff", 0)

        assert repo.upsert_transcript(
            known, "transcript", TranscriptSource.GENERATED
        ).accepted
        assert (
            repo.upsert_transcript(
                orphan_position, "transcript", TranscriptSource.GENERATED
            ).status
            is TranscriptUpsertStatus.UNKNOWN_REFERENCE
        )
        assert (
            repo.upsert_transcript(
                orphan_session, "transcript", TranscriptSource.GENERATED
            ).status
            is TranscriptUpsertStatus.UNKNOWN_REFERENCE
        )

    def test_rejects_directory_reference_when_payload_session_differs(
        self, tmp_path: Path
    ) -> None:
        journal_root = tmp_path / "journal"
        enclosing_dir = "20260801-120000-aaaa"
        payload_session = "20260801-120000-bbbb"
        session_dir = journal_root / enclosing_dir
        session_dir.mkdir(parents=True)
        event = JournalEvent(
            session_id=payload_session,
            timestamp="2026-08-01T12:00:00+01:00",
            source="voice",
            role="user",
            text="привет",
            media=(),
            transcript=None,
        )
        (session_dir / "events.jsonl").write_text(
            event.to_json_line(), encoding="utf-8"
        )

        store = JournalStore(journal_root)
        repo = TranscriptOverlayRepository(
            tmp_path / "derived", JournalStoreEventReferenceResolver(store)
        )

        # The enclosing directory's reference has no matching raw event; only
        # the payload's own reference does.
        assert (
            repo.upsert_transcript(
                JournalEventRef(enclosing_dir, 0),
                "transcript",
                TranscriptSource.GENERATED,
            ).status
            is TranscriptUpsertStatus.UNKNOWN_REFERENCE
        )

    def test_raw_event_accepted_without_building_corpus(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        reference = store.append(
            JournalEvent(
                session_id="20260801-120000-ab12",
                timestamp="2026-08-01T12:00:00+01:00",
                source="voice",
                role="user",
                text="привет",
                media=(),
                transcript=None,
            )
        )
        # Deliberately do NOT build any corpus/derived projection: the raw
        # journal alone is authoritative for reference validity.
        repo = TranscriptOverlayRepository(
            tmp_path / "derived", JournalStoreEventReferenceResolver(store)
        )

        result = repo.upsert_transcript(
            reference, "transcript", TranscriptSource.GENERATED
        )
        assert result.accepted
        assert repo.read_transcript(reference).found
