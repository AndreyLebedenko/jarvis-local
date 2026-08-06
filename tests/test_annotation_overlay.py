from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from jarvis.core.bus import EventBus
from jarvis.journal.annotation import (
    ANNOTATION_MAX_AUTHOR_LENGTH,
    ANNOTATION_MAX_METADATA_ENTRIES,
    ANNOTATION_MAX_METADATA_SERIALIZED_LENGTH,
    ANNOTATION_MAX_PER_SESSION,
    ANNOTATION_MAX_TEXT_LENGTH,
    AnnotationDeleteStatus,
    AnnotationOverlayRepository,
    AnnotationOverlaySchemaError,
    AnnotationReadStatus,
    AnnotationSource,
    AnnotationStatus,
    AnnotationTarget,
    AnnotationWriteStatus,
)
from jarvis.journal.events import JournalEvent, JournalEventRecord, JournalEventRef
from jarvis.journal.lifecycle import (
    AnnotationHistoryProjection,
    CorpusHistoryProjection,
    HistoryProjectionLifecycle,
    JournalHistoryService,
    JournalStoreEventReferenceResolver,
    UnavailableSemanticHistoryProjection,
)
from jarvis.journal.search import JournalSearchIndex
from jarvis.journal.store import JournalStore

_SESSION = "20260801-120000-ab12"


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


def _repo(
    tmp_path: Path, references: _FakeReferences | None = None
) -> AnnotationOverlayRepository:
    return AnnotationOverlayRepository(
        tmp_path / "derived", references or _FakeReferences()
    )


def _session_target(session_id: str = _SESSION) -> AnnotationTarget:
    return AnnotationTarget(session_id)


def _range_target(start: int, end: int, session_id: str = _SESSION) -> AnnotationTarget:
    return AnnotationTarget(session_id, start, end)


def _append_event(
    store: JournalStore, session_id: str, text: str = "hello"
) -> JournalEventRef:
    return store.append(
        JournalEvent(
            session_id=session_id,
            timestamp="2026-08-01T12:00:00+01:00",
            source="voice",
            role="user",
            text=text,
            media=(),
            transcript=None,
        )
    )


def _journal_bytes(root: Path) -> dict[str, bytes]:
    """Snapshot every raw ``events.jsonl`` under the journal store root."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("events.jsonl"))
    }


class TestAddAndRead:
    def test_add_whole_session_annotation(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _session_target(),
            "a summary of the session",
            author="assistant",
            source=AnnotationSource.GENERATED,
        )
        assert result.accepted
        assert result.annotation_id is not None

        read = repo.read_annotation(result.annotation_id)
        assert read.found
        assert read.annotation is not None
        annotation = read.annotation
        assert annotation.annotation_id == result.annotation_id
        assert annotation.target == _session_target()
        assert annotation.target.is_whole_session
        assert annotation.text == "a summary of the session"
        assert annotation.author == "assistant"
        assert annotation.source is AnnotationSource.GENERATED
        assert annotation.status is AnnotationStatus.ACTIVE
        assert annotation.metadata == {}
        assert annotation.created_at
        assert annotation.updated_at

    def test_add_event_range_annotation(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _range_target(2, 5),
            "notes on turns 2-5",
            author="user",
            source=AnnotationSource.EDITED,
            status=AnnotationStatus.ACTIVE,
            metadata={"topic": "budget", "confidence": 3},
        )
        assert result.accepted
        assert result.annotation_id is not None

        annotation = repo.read_annotation(result.annotation_id).annotation
        assert annotation is not None
        assert annotation.target.start_position == 2
        assert annotation.target.end_position == 5
        assert not annotation.target.is_whole_session
        assert annotation.metadata == {"topic": "budget", "confidence": 3}
        assert annotation.author == "user"
        assert annotation.source is AnnotationSource.EDITED

    def test_add_stores_unicode_text(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        text = "Заметка о разговоре. 你好"
        result = repo.add_annotation(
            _session_target(), text, "assistant", AnnotationSource.GENERATED
        )
        annotation = repo.read_annotation(result.annotation_id or "").annotation
        assert annotation is not None
        assert annotation.text == text

    def test_multiple_annotations_per_session_have_distinct_ids(
        self, tmp_path: Path
    ) -> None:
        repo = _repo(tmp_path)
        first = repo.add_annotation(
            _session_target(), "first", "assistant", AnnotationSource.GENERATED
        )
        second = repo.add_annotation(
            _range_target(0, 1), "second", "assistant", AnnotationSource.GENERATED
        )
        assert first.annotation_id != second.annotation_id
        assert repo.count() == 2

    def test_read_missing_annotation_returns_not_found(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        read = repo.read_annotation("does-not-exist")
        assert not read.found
        assert read.status is AnnotationReadStatus.NOT_FOUND
        assert read.annotation is None

    def test_read_returns_not_found_when_no_db(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert repo.read_annotation("x").status is AnnotationReadStatus.NOT_FOUND


class TestTargetValidation:
    def test_rejects_unknown_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _FakeReferences(known=set()))
        result = repo.add_annotation(
            _session_target(), "orphan", "assistant", AnnotationSource.GENERATED
        )
        assert result.status is AnnotationWriteStatus.UNKNOWN_REFERENCE
        assert repo.count() == 0

    def test_rejects_unknown_event_range(self, tmp_path: Path) -> None:
        known = {JournalEventRef(_SESSION, 0)}
        repo = _repo(tmp_path, _FakeReferences(known=known))
        result = repo.add_annotation(
            _range_target(0, 9), "orphan", "assistant", AnnotationSource.GENERATED
        )
        assert result.status is AnnotationWriteStatus.UNKNOWN_REFERENCE

    def test_accepts_known_event_range(self, tmp_path: Path) -> None:
        known = {JournalEventRef(_SESSION, position) for position in range(6)}
        repo = _repo(tmp_path, _FakeReferences(known=known))
        result = repo.add_annotation(
            _range_target(2, 5), "known", "assistant", AnnotationSource.GENERATED
        )
        assert result.accepted

    def test_rejects_mixed_none_target(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            AnnotationTarget(_SESSION, 2, None),
            "bad",
            "assistant",
            AnnotationSource.GENERATED,
        )
        assert result.status is AnnotationWriteStatus.INVALID_TARGET
        assert repo.count() == 0

    def test_rejects_reversed_range(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _range_target(5, 2), "bad", "assistant", AnnotationSource.GENERATED
        )
        assert result.status is AnnotationWriteStatus.INVALID_TARGET

    def test_rejects_negative_position(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            AnnotationTarget(_SESSION, -1, 2),
            "bad",
            "assistant",
            AnnotationSource.GENERATED,
        )
        assert result.status is AnnotationWriteStatus.INVALID_TARGET

    def test_rejects_malformed_session_id(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            AnnotationTarget("not-a-session"),
            "bad",
            "assistant",
            AnnotationSource.GENERATED,
        )
        assert result.status is AnnotationWriteStatus.UNKNOWN_REFERENCE

    def test_whole_session_probes_position_zero(self, tmp_path: Path) -> None:
        references = _FakeReferences(known={JournalEventRef(_SESSION, 0)})
        repo = _repo(tmp_path, references)
        repo.add_annotation(
            _session_target(), "text", "assistant", AnnotationSource.GENERATED
        )
        assert references.queried == [JournalEventRef(_SESSION, 0)]


class TestContentValidation:
    def test_rejects_empty_text(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _session_target(), "", "assistant", AnnotationSource.GENERATED
        )
        assert result.status is AnnotationWriteStatus.TEXT_EMPTY

    def test_rejects_over_limit_text(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _session_target(),
            "x" * (ANNOTATION_MAX_TEXT_LENGTH + 1),
            "assistant",
            AnnotationSource.GENERATED,
        )
        assert result.status is AnnotationWriteStatus.TEXT_TOO_LONG

    def test_accepts_text_at_limit(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _session_target(),
            "x" * ANNOTATION_MAX_TEXT_LENGTH,
            "assistant",
            AnnotationSource.GENERATED,
        )
        assert result.accepted

    def test_rejects_empty_author(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _session_target(), "text", "", AnnotationSource.GENERATED
        )
        assert result.status is AnnotationWriteStatus.AUTHOR_EMPTY

    def test_rejects_over_limit_author(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _session_target(),
            "text",
            "a" * (ANNOTATION_MAX_AUTHOR_LENGTH + 1),
            AnnotationSource.GENERATED,
        )
        assert result.status is AnnotationWriteStatus.AUTHOR_TOO_LONG


class TestMetadataLimits:
    def test_rejects_too_many_metadata_entries(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        metadata = {f"k{i}": i for i in range(ANNOTATION_MAX_METADATA_ENTRIES + 1)}
        result = repo.add_annotation(
            _session_target(),
            "text",
            "assistant",
            AnnotationSource.GENERATED,
            metadata=metadata,
        )
        assert result.status is AnnotationWriteStatus.METADATA_TOO_LARGE
        assert repo.count() == 0

    def test_rejects_oversize_serialized_metadata(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        big_value = "y" * (ANNOTATION_MAX_METADATA_SERIALIZED_LENGTH + 1)
        result = repo.add_annotation(
            _session_target(),
            "text",
            "assistant",
            AnnotationSource.GENERATED,
            metadata={"blob": big_value},
        )
        assert result.status is AnnotationWriteStatus.METADATA_TOO_LARGE

    def test_rejects_non_serializable_metadata(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.add_annotation(
            _session_target(),
            "text",
            "assistant",
            AnnotationSource.GENERATED,
            metadata={"bad": {1, 2, 3}},  # type: ignore[dict-item]
        )
        assert result.status is AnnotationWriteStatus.METADATA_INVALID

    def test_accepts_metadata_at_entry_limit(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        metadata = {f"k{i}": i for i in range(ANNOTATION_MAX_METADATA_ENTRIES)}
        result = repo.add_annotation(
            _session_target(),
            "text",
            "assistant",
            AnnotationSource.GENERATED,
            metadata=metadata,
        )
        assert result.accepted


class TestCountLimit:
    def test_rejects_over_session_count_limit(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        for _ in range(ANNOTATION_MAX_PER_SESSION):
            assert repo.add_annotation(
                _session_target(), "text", "assistant", AnnotationSource.GENERATED
            ).accepted
        overflow = repo.add_annotation(
            _session_target(), "one too many", "assistant", AnnotationSource.GENERATED
        )
        assert overflow.status is AnnotationWriteStatus.TOO_MANY_ANNOTATIONS
        assert repo.count() == ANNOTATION_MAX_PER_SESSION

    def test_count_limit_is_per_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        other = "20260802-100000-cd34"
        for _ in range(ANNOTATION_MAX_PER_SESSION):
            repo.add_annotation(
                _session_target(), "text", "assistant", AnnotationSource.GENERATED
            )
        result = repo.add_annotation(
            _session_target(other), "text", "assistant", AnnotationSource.GENERATED
        )
        assert result.accepted


class TestUpdate:
    def test_update_text_and_status(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        created = repo.add_annotation(
            _session_target(), "first", "assistant", AnnotationSource.GENERATED
        )
        assert created.annotation_id is not None
        first = repo.read_annotation(created.annotation_id).annotation
        assert first is not None

        updated = repo.update_annotation(
            created.annotation_id,
            text="corrected",
            status=AnnotationStatus.DISMISSED,
            source=AnnotationSource.EDITED,
        )
        assert updated.accepted
        after = repo.read_annotation(created.annotation_id).annotation
        assert after is not None
        assert after.text == "corrected"
        assert after.status is AnnotationStatus.DISMISSED
        assert after.source is AnnotationSource.EDITED
        assert after.created_at == first.created_at
        assert after.updated_at >= first.updated_at

    def test_update_unknown_annotation(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        result = repo.update_annotation("missing", text="x")
        assert result.status is AnnotationWriteStatus.UNKNOWN_ANNOTATION

    def test_update_rejects_empty_text(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        created = repo.add_annotation(
            _session_target(), "first", "assistant", AnnotationSource.GENERATED
        )
        assert created.annotation_id is not None
        result = repo.update_annotation(created.annotation_id, text="")
        assert result.status is AnnotationWriteStatus.TEXT_EMPTY

    def test_update_preserves_target(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        created = repo.add_annotation(
            _range_target(1, 3), "first", "assistant", AnnotationSource.GENERATED
        )
        assert created.annotation_id is not None
        repo.update_annotation(created.annotation_id, text="second")
        after = repo.read_annotation(created.annotation_id).annotation
        assert after is not None
        assert after.target == _range_target(1, 3)


class TestDelete:
    def test_delete_existing(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        created = repo.add_annotation(
            _session_target(), "text", "assistant", AnnotationSource.GENERATED
        )
        assert created.annotation_id is not None
        result = repo.delete_annotation(created.annotation_id)
        assert result.status is AnnotationDeleteStatus.DELETED
        assert not repo.read_annotation(created.annotation_id).found

    def test_delete_missing_returns_not_found(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        assert (
            repo.delete_annotation("missing").status is AnnotationDeleteStatus.NOT_FOUND
        )

    def test_delete_no_db_returns_not_found(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert (
            repo.delete_annotation("missing").status is AnnotationDeleteStatus.NOT_FOUND
        )


class TestSessionDelete:
    def test_session_delete_removes_only_that_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        other = "20260802-100000-cd34"
        repo.add_annotation(
            _session_target(), "a", "assistant", AnnotationSource.GENERATED
        )
        repo.add_annotation(
            _range_target(0, 1), "b", "assistant", AnnotationSource.GENERATED
        )
        kept = repo.add_annotation(
            _session_target(other), "c", "assistant", AnnotationSource.GENERATED
        )

        repo.delete_session(_SESSION)

        assert repo.read_session_annotations(_SESSION) == ()
        assert kept.annotation_id is not None
        assert repo.read_annotation(kept.annotation_id).found

    def test_session_delete_no_db_is_noop(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.delete_session(_SESSION)

    def test_session_delete_empty_is_noop(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        repo.delete_session(_SESSION)


class TestReadSessionAnnotations:
    def test_returns_annotations_ordered_by_creation(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        first = repo.add_annotation(
            _session_target(), "first", "assistant", AnnotationSource.GENERATED
        )
        second = repo.add_annotation(
            _range_target(0, 1), "second", "assistant", AnnotationSource.EDITED
        )
        annotations = repo.read_session_annotations(_SESSION)
        assert [a.annotation_id for a in annotations] == [
            first.annotation_id,
            second.annotation_id,
        ]
        assert [a.text for a in annotations] == ["first", "second"]

    def test_returns_empty_for_unknown_session(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert repo.read_session_annotations(_SESSION) == ()

    def test_returns_empty_when_no_db(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert repo.read_session_annotations(_SESSION) == ()


class TestRebuildAndCount:
    def test_rebuild_creates_schema(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        assert repo.db_path.exists()
        assert repo.count() == 0

    def test_rebuild_preserves_existing_data(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        created = repo.add_annotation(
            _session_target(), "keep me", "assistant", AnnotationSource.GENERATED
        )
        repo.rebuild()
        assert created.annotation_id is not None
        assert repo.read_annotation(created.annotation_id).found

    def test_rebuild_idempotent(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        repo.rebuild()
        assert repo.count() == 0

    def test_count_no_db(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        assert repo.count() == 0


class TestSchemaVersion:
    def test_newer_schema_version_raises(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        with closing(sqlite3.connect(repo.db_path)) as conn, conn:
            conn.execute(
                "UPDATE annotation_overlay_meta SET value = ? WHERE key = ?",
                ("999", "schema_version"),
            )
        with pytest.raises(AnnotationOverlaySchemaError, match="newer schema"):
            repo.read_annotation("x")

    def test_invalid_schema_version_raises(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        repo.rebuild()
        with closing(sqlite3.connect(repo.db_path)) as conn, conn:
            conn.execute(
                "UPDATE annotation_overlay_meta SET value = ? WHERE key = ?",
                ("not_a_number", "schema_version"),
            )
        with pytest.raises(AnnotationOverlaySchemaError, match="Invalid"):
            repo.read_annotation("x")


class TestProjectionLifecycle:
    def test_projection_name(self, tmp_path: Path) -> None:
        projection = AnnotationHistoryProjection(_repo(tmp_path))
        assert projection.name == "annotation"

    def test_projection_rebuild_creates_schema(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        AnnotationHistoryProjection(repo).rebuild()
        assert repo.db_path.exists()

    def test_projection_project_event_is_noop(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        projection = AnnotationHistoryProjection(repo)
        projection.rebuild()
        record = JournalEventRecord(
            JournalEventRef(_SESSION, 0),
            JournalEvent(
                session_id=_SESSION,
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
        repo.add_annotation(
            _session_target(), "text", "assistant", AnnotationSource.GENERATED
        )
        AnnotationHistoryProjection(repo).delete_session_projection(_SESSION)
        assert repo.read_session_annotations(_SESSION) == ()


class TestRawJournalUnchanged:
    def test_annotation_writes_leave_raw_jsonl_bytes_unchanged(
        self, tmp_path: Path
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        for position in range(3):
            _append_event(store, _SESSION, text=f"turn {position}")
        # Production layout: the overlay DB shares the journal store root,
        # exactly as build_app() wires it - so this exercises the real root,
        # not an unrelated derived directory.
        repo = AnnotationOverlayRepository(
            store.root, JournalStoreEventReferenceResolver(store)
        )
        before = _journal_bytes(store.root)
        assert before  # guard against asserting over an empty snapshot

        assert repo.add_annotation(
            _session_target(),
            "whole-session note",
            "assistant",
            AnnotationSource.GENERATED,
        ).accepted
        assert repo.add_annotation(
            _range_target(0, 2), "range note", "assistant", AnnotationSource.EDITED
        ).accepted
        assert repo.update_annotation(
            repo.read_session_annotations(_SESSION)[0].annotation_id, text="edited"
        ).accepted

        assert repo.db_path.parent == store.root
        assert repo.db_path.exists()
        assert _journal_bytes(store.root) == before


class TestSessionDeletionThroughService:
    def test_service_delete_session_removes_annotations(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = JournalStore(tmp_path / "journal")
        deleted, kept = _SESSION, "20260802-100000-cd34"
        for session_id in (deleted, kept):
            _append_event(store, session_id, text="answer")

        search_index = JournalSearchIndex(store, store.root)
        corpus = search_index.repository
        annotation_repo = AnnotationOverlayRepository(
            store.root, JournalStoreEventReferenceResolver(store)
        )
        lifecycle = HistoryProjectionLifecycle(
            bus,
            projections=(
                CorpusHistoryProjection(corpus),
                AnnotationHistoryProjection(annotation_repo),
            ),
            semantic_projection=UnavailableSemanticHistoryProjection(),
        )
        corpus.rebuild()
        annotation_repo.rebuild()
        service = JournalHistoryService(store, lifecycle, search_index)

        for session_id in (deleted, kept):
            assert annotation_repo.add_annotation(
                _session_target(session_id),
                "note",
                "assistant",
                AnnotationSource.GENERATED,
            ).accepted

        service.delete_session(deleted)

        assert annotation_repo.read_session_annotations(deleted) == ()
        assert len(annotation_repo.read_session_annotations(kept)) == 1
        assert [summary.session_id for summary in service.list_sessions()] == [kept]


class TestJournalStoreReferenceResolver:
    def test_known_reference_accepted_orphans_rejected(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        store.append(
            JournalEvent(
                session_id=_SESSION,
                timestamp="2026-08-01T12:00:00+01:00",
                source="voice",
                role="user",
                text="привет",
                media=(),
                transcript=None,
            )
        )
        repo = AnnotationOverlayRepository(
            tmp_path / "derived", JournalStoreEventReferenceResolver(store)
        )

        assert repo.add_annotation(
            _session_target(), "note", "assistant", AnnotationSource.GENERATED
        ).accepted
        assert (
            repo.add_annotation(
                _range_target(0, 5), "note", "assistant", AnnotationSource.GENERATED
            ).status
            is AnnotationWriteStatus.UNKNOWN_REFERENCE
        )
        assert (
            repo.add_annotation(
                _session_target("20260901-090000-ffff"),
                "note",
                "assistant",
                AnnotationSource.GENERATED,
            ).status
            is AnnotationWriteStatus.UNKNOWN_REFERENCE
        )
