from __future__ import annotations

from pathlib import Path

from jarvis.journal.archive import (
    ArchiveMediaOutcome,
    ArchiveOverlayRepository,
    ArchiveReadStatus,
    ArchiveRun,
    ConsolidationRunStatus,
    MediaOutcome,
    utc_now_iso,
)
from jarvis.journal.events import JournalEvent, JournalEventRecord, JournalEventRef
from jarvis.journal.lifecycle import ArchiveHistoryProjection

_SESSION = "20260801-120000-ab12"


def _run(
    session_id: str = _SESSION,
    *,
    status: ConsolidationRunStatus = ConsolidationRunStatus.COMPLETED,
    bytes_reclaimed: int = 1234,
    outcomes: tuple[ArchiveMediaOutcome, ...] = (),
) -> ArchiveRun:
    now = utc_now_iso()
    return ArchiveRun(
        session_id=session_id,
        status=status,
        event_count=3,
        annotation_count=1,
        media_outcomes=outcomes,
        bytes_reclaimed=bytes_reclaimed,
        started_at=now,
        completed_at=now,
    )


def test_read_run_for_unknown_session_reports_not_found(tmp_path: Path) -> None:
    repository = ArchiveOverlayRepository(tmp_path)
    read = repository.read_run(_SESSION)
    assert read.status is ArchiveReadStatus.NOT_FOUND
    assert not read.found


def test_record_and_read_round_trips_a_run_with_media_outcomes(
    tmp_path: Path,
) -> None:
    repository = ArchiveOverlayRepository(tmp_path)
    outcomes = (
        ArchiveMediaOutcome(
            JournalEventRef(_SESSION, 0),
            "utterance-0001.wav",
            MediaOutcome.REMOVED,
            "transcribed",
        ),
        ArchiveMediaOutcome(
            JournalEventRef(_SESSION, 1),
            "utterance-0002.wav",
            MediaOutcome.KEPT,
            "no_transcript",
        ),
    )
    repository.record_run(_run(outcomes=outcomes))

    read = repository.read_run(_SESSION)
    assert read.found
    run = read.run
    assert run is not None
    assert run.status is ConsolidationRunStatus.COMPLETED
    assert run.media_outcomes == outcomes
    assert run.removed_count == 1
    assert run.failed_count == 0


def test_record_run_upserts_a_single_row_per_session(tmp_path: Path) -> None:
    """A run overwrites the prior result for the session - this store keeps
    only the latest outcome, not a history of every attempt (owner-decided
    idempotent-recovery design, task v1.8.0-25)."""
    repository = ArchiveOverlayRepository(tmp_path)
    repository.record_run(
        _run(status=ConsolidationRunStatus.PARTIAL_FAILURE, bytes_reclaimed=100)
    )
    repository.record_run(
        _run(status=ConsolidationRunStatus.COMPLETED, bytes_reclaimed=500)
    )

    read = repository.read_run(_SESSION)
    assert read.run is not None
    assert read.run.status is ConsolidationRunStatus.COMPLETED
    assert read.run.bytes_reclaimed == 500


def test_delete_session_clears_its_run(tmp_path: Path) -> None:
    repository = ArchiveOverlayRepository(tmp_path)
    repository.record_run(_run())
    assert repository.read_run(_SESSION).found

    repository.delete_session(_SESSION)

    assert not repository.read_run(_SESSION).found


def test_delete_session_is_a_no_op_when_nothing_was_recorded(tmp_path: Path) -> None:
    repository = ArchiveOverlayRepository(tmp_path)
    repository.delete_session(_SESSION)  # must not raise
    assert not repository.read_run(_SESSION).found


def test_runs_for_different_sessions_do_not_collide(tmp_path: Path) -> None:
    repository = ArchiveOverlayRepository(tmp_path)
    other_session = "20260802-090000-cd34"
    repository.record_run(_run(_SESSION, bytes_reclaimed=10))
    repository.record_run(_run(other_session, bytes_reclaimed=20))

    repository.delete_session(_SESSION)

    assert not repository.read_run(_SESSION).found
    other = repository.read_run(other_session)
    assert other.found
    assert other.run is not None
    assert other.run.bytes_reclaimed == 20


def test_rebuild_is_safe_on_an_empty_store(tmp_path: Path) -> None:
    repository = ArchiveOverlayRepository(tmp_path)
    repository.rebuild()  # must not raise
    assert not repository.read_run(_SESSION).found


class TestProjectionLifecycle:
    def test_projection_name(self, tmp_path: Path) -> None:
        projection = ArchiveHistoryProjection(ArchiveOverlayRepository(tmp_path))
        assert projection.name == "archive"

    def test_projection_rebuild_creates_schema(self, tmp_path: Path) -> None:
        repository = ArchiveOverlayRepository(tmp_path)
        ArchiveHistoryProjection(repository).rebuild()
        assert repository.db_path.exists()

    def test_projection_project_event_is_noop(self, tmp_path: Path) -> None:
        repository = ArchiveOverlayRepository(tmp_path)
        projection = ArchiveHistoryProjection(repository)
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
        assert not repository.read_run(_SESSION).found

    def test_projection_delete_session(self, tmp_path: Path) -> None:
        repository = ArchiveOverlayRepository(tmp_path)
        repository.record_run(_run())
        ArchiveHistoryProjection(repository).delete_session_projection(_SESSION)
        assert not repository.read_run(_SESSION).found
