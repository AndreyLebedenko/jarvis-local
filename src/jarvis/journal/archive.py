"""Archive metadata overlay store (task v1.8.0-25).

Records the *result* of the most recent far-consolidation run for a session:
what happened to each audio file, how many bytes were reclaimed, and whether
the run completed cleanly or hit a partial failure. This is the "archive
metadata" derived-corpus category the story names alongside transcripts and
annotations.

Design decided with the owner before implementation (2026-08-08): this store
is not a step-by-step recovery log. Crash/restart recovery is idempotent
re-derivation - the executor always re-plans fresh through
`ConsolidationPlanner` before acting, and an already-removed file resolves to
`MediaActionReason.ALREADY_ABSENT` on the next plan, so a partial prior run's
remaining work is simply what a fresh plan still proposes. This store exists
for audit and UI visibility only: one row per session, upserted (overwritten)
by each run, holding the latest outcome - never an in-progress state and never
a history of every past attempt.

Like the transcript and annotation overlays, this store is never derived from
an appended raw event (a run is written only by the explicit executor), so its
`ArchiveHistoryProjection.project_event` is a no-op; only session deletion
touches it.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from jarvis.journal.events import JournalEventRef

CURRENT_ARCHIVE_OVERLAY_SCHEMA_VERSION = 1
ARCHIVE_OVERLAY_DB_NAME = "archive_overlays.db"
_SCHEMA_VERSION_KEY = "schema_version"


class ArchiveOverlaySchemaError(Exception):
    pass


class ConsolidationRunStatus(Enum):
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"


class MediaOutcome(Enum):
    REMOVED = "removed"
    KEPT = "kept"
    FAILED = "failed"


@dataclass(frozen=True)
class ArchiveMediaOutcome:
    reference: JournalEventRef
    media: str
    outcome: MediaOutcome
    detail: str


@dataclass(frozen=True)
class ArchiveRun:
    session_id: str
    status: ConsolidationRunStatus
    event_count: int
    annotation_count: int
    media_outcomes: tuple[ArchiveMediaOutcome, ...]
    bytes_reclaimed: int
    started_at: str
    completed_at: str

    @property
    def removed_count(self) -> int:
        return sum(
            1 for item in self.media_outcomes if item.outcome is MediaOutcome.REMOVED
        )

    @property
    def failed_count(self) -> int:
        return sum(
            1 for item in self.media_outcomes if item.outcome is MediaOutcome.FAILED
        )


class ArchiveReadStatus(Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class ArchiveRunRead:
    status: ArchiveReadStatus
    run: ArchiveRun | None = None

    @property
    def found(self) -> bool:
        return self.status is ArchiveReadStatus.FOUND


class ArchiveOverlayRepository:
    def __init__(self, root: Path) -> None:
        self._db_path = root / ARCHIVE_OVERLAY_DB_NAME

    @property
    def db_path(self) -> Path:
        return self._db_path

    def record_run(self, run: ArchiveRun) -> None:
        outcomes_json = _encode_outcomes(run.media_outcomes)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO archive_runs
                    (session_id, status, event_count, annotation_count,
                     media_outcomes, bytes_reclaimed, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = excluded.status,
                    event_count = excluded.event_count,
                    annotation_count = excluded.annotation_count,
                    media_outcomes = excluded.media_outcomes,
                    bytes_reclaimed = excluded.bytes_reclaimed,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at
                """,
                (
                    run.session_id,
                    run.status.value,
                    run.event_count,
                    run.annotation_count,
                    outcomes_json,
                    run.bytes_reclaimed,
                    run.started_at,
                    run.completed_at,
                ),
            )

    def read_run(self, session_id: str) -> ArchiveRunRead:
        connection = self._open_read_connection()
        if connection is None:
            return ArchiveRunRead(ArchiveReadStatus.NOT_FOUND)
        with closing(connection):
            if not _table_exists(connection, "archive_runs"):
                return ArchiveRunRead(ArchiveReadStatus.NOT_FOUND)
            row = connection.execute(
                """
                SELECT session_id, status, event_count, annotation_count,
                       media_outcomes, bytes_reclaimed, started_at, completed_at
                FROM archive_runs
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return ArchiveRunRead(ArchiveReadStatus.NOT_FOUND)
        return ArchiveRunRead(ArchiveReadStatus.FOUND, _row_to_run(row))

    def delete_session(self, session_id: str) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            connection.execute(
                "DELETE FROM archive_runs WHERE session_id = ?",
                (session_id,),
            )

    def rebuild(self) -> None:
        self._check_existing_schema_version()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if _table_exists(connection, "archive_overlay_meta"):
            self._check_schema_version(connection)
            return
        self._create_schema(connection)

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_overlay_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO archive_overlay_meta (key, value)
            VALUES (?, ?)
            """,
            (_SCHEMA_VERSION_KEY, str(CURRENT_ARCHIVE_OVERLAY_SCHEMA_VERSION)),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_runs (
                session_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                annotation_count INTEGER NOT NULL,
                media_outcomes TEXT NOT NULL,
                bytes_reclaimed INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL
            )
            """
        )

    def _check_existing_schema_version(self) -> None:
        if not self._db_path.exists():
            return
        with closing(_connect_read_only(self._db_path)) as connection:
            self._check_schema_version(connection)

    def _check_schema_version(self, connection: sqlite3.Connection) -> None:
        if not _table_exists(connection, "archive_overlay_meta"):
            return
        row = connection.execute(
            "SELECT value FROM archive_overlay_meta WHERE key = ?",
            (_SCHEMA_VERSION_KEY,),
        ).fetchone()
        if row is None:
            return
        try:
            version = int(row[0])
        except ValueError as exc:
            raise ArchiveOverlaySchemaError(
                f"Invalid archive overlay schema version: {row[0]!r}"
            ) from exc
        if version > CURRENT_ARCHIVE_OVERLAY_SCHEMA_VERSION:
            raise ArchiveOverlaySchemaError(
                "Archive overlay database uses a newer schema version: "
                f"{version} > {CURRENT_ARCHIVE_OVERLAY_SCHEMA_VERSION}"
            )

    def _open_read_connection(self) -> sqlite3.Connection | None:
        if not self._db_path.exists():
            return None
        connection = _connect_read_only(self._db_path)
        try:
            self._check_schema_version(connection)
            return connection
        except Exception:
            connection.close()
            raise


def _encode_outcomes(outcomes: tuple[ArchiveMediaOutcome, ...]) -> str:
    return json.dumps(
        [
            {
                "session_id": item.reference.session_id,
                "event_position": item.reference.event_position,
                "media": item.media,
                "outcome": item.outcome.value,
                "detail": item.detail,
            }
            for item in outcomes
        ],
        ensure_ascii=False,
    )


def _decode_outcomes(payload: str) -> tuple[ArchiveMediaOutcome, ...]:
    return tuple(
        ArchiveMediaOutcome(
            reference=JournalEventRef(
                str(entry["session_id"]), int(entry["event_position"])
            ),
            media=str(entry["media"]),
            outcome=MediaOutcome(str(entry["outcome"])),
            detail=str(entry["detail"]),
        )
        for entry in json.loads(payload)
    )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _row_to_run(row: tuple[object, ...]) -> ArchiveRun:
    return ArchiveRun(
        session_id=str(row[0]),
        status=ConsolidationRunStatus(str(row[1])),
        event_count=int(row[2]),
        annotation_count=int(row[3]),
        media_outcomes=_decode_outcomes(str(row[4])),
        bytes_reclaimed=int(row[5]),
        started_at=str(row[6]),
        completed_at=str(row[7]),
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
