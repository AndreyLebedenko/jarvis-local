"""Transcript overlay store: editable derived transcripts keyed by event reference."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from jarvis.journal.events import JournalEventRef


class EventReferenceResolver(Protocol):
    """Decides whether a source event actually exists for a reference.

    Keeps the transcript store from persisting overlays for events that have
    no legacy journal entry, without coupling it to a concrete backbone.
    """

    def event_exists(self, reference: JournalEventRef) -> bool: ...


CURRENT_TRANSCRIPT_OVERLAY_SCHEMA_VERSION = 1
TRANSCRIPT_OVERLAY_DB_NAME = "transcript_overlays.db"
TRANSCRIPT_MAX_TEXT_LENGTH = 20_000
_SCHEMA_VERSION_KEY = "schema_version"


class TranscriptOverlaySchemaError(Exception):
    pass


class TranscriptSource(Enum):
    RAW = "raw"
    GENERATED = "generated"
    EDITED = "edited"


class TranscriptReadStatus(Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"


class TranscriptUpsertStatus(Enum):
    ACCEPTED = "accepted"
    UNKNOWN_REFERENCE = "unknown_reference"
    TEXT_TOO_LONG = "text_too_long"
    TEXT_EMPTY = "text_empty"
    INVALID_SOURCE = "invalid_source"


class TranscriptDeleteStatus(Enum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class TranscriptOverlay:
    reference: JournalEventRef
    text: str
    source: TranscriptSource
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TranscriptOverlayRead:
    status: TranscriptReadStatus
    overlay: TranscriptOverlay | None = None

    @property
    def found(self) -> bool:
        return self.status is TranscriptReadStatus.FOUND


@dataclass(frozen=True)
class TranscriptUpsertResult:
    status: TranscriptUpsertStatus

    @property
    def accepted(self) -> bool:
        return self.status is TranscriptUpsertStatus.ACCEPTED


@dataclass(frozen=True)
class TranscriptDeleteResult:
    status: TranscriptDeleteStatus


class TranscriptOverlayRepository:
    def __init__(self, root: Path, references: EventReferenceResolver) -> None:
        self._db_path = root / TRANSCRIPT_OVERLAY_DB_NAME
        self._references = references

    @property
    def db_path(self) -> Path:
        return self._db_path

    def read_transcript(self, reference: JournalEventRef) -> TranscriptOverlayRead:
        connection = self._open_read_connection()
        if connection is None:
            return TranscriptOverlayRead(TranscriptReadStatus.NOT_FOUND)
        with closing(connection):
            if not _table_exists(connection, "transcript_overlays"):
                return TranscriptOverlayRead(TranscriptReadStatus.NOT_FOUND)
            row = connection.execute(
                """
                SELECT session_id, event_position, text, source,
                       created_at, updated_at
                FROM transcript_overlays
                WHERE session_id = ? AND event_position = ?
                """,
                (reference.session_id, reference.event_position),
            ).fetchone()
        if row is None:
            return TranscriptOverlayRead(TranscriptReadStatus.NOT_FOUND)
        return TranscriptOverlayRead(TranscriptReadStatus.FOUND, _row_to_overlay(row))

    def read_session_transcripts(
        self, session_id: str
    ) -> tuple[TranscriptOverlay, ...]:
        connection = self._open_read_connection()
        if connection is None:
            return ()
        with closing(connection):
            if not _table_exists(connection, "transcript_overlays"):
                return ()
            rows = connection.execute(
                """
                SELECT session_id, event_position, text, source,
                       created_at, updated_at
                FROM transcript_overlays
                WHERE session_id = ?
                ORDER BY event_position
                """,
                (session_id,),
            ).fetchall()
        return tuple(_row_to_overlay(row) for row in rows)

    def upsert_transcript(
        self,
        reference: JournalEventRef,
        text: str,
        source: TranscriptSource,
    ) -> TranscriptUpsertResult:
        if not text:
            return TranscriptUpsertResult(TranscriptUpsertStatus.TEXT_EMPTY)
        if len(text) > TRANSCRIPT_MAX_TEXT_LENGTH:
            return TranscriptUpsertResult(TranscriptUpsertStatus.TEXT_TOO_LONG)
        if not isinstance(source, TranscriptSource):
            return TranscriptUpsertResult(TranscriptUpsertStatus.INVALID_SOURCE)
        if not self._references.event_exists(reference):
            return TranscriptUpsertResult(TranscriptUpsertStatus.UNKNOWN_REFERENCE)

        now = _utc_now_iso()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            existing = connection.execute(
                """
                SELECT created_at
                FROM transcript_overlays
                WHERE session_id = ? AND event_position = ?
                """,
                (reference.session_id, reference.event_position),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE transcript_overlays
                    SET text = ?, source = ?, updated_at = ?
                    WHERE session_id = ? AND event_position = ?
                    """,
                    (
                        text,
                        source.value,
                        now,
                        reference.session_id,
                        reference.event_position,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO transcript_overlays
                        (session_id, event_position, text, source,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reference.session_id,
                        reference.event_position,
                        text,
                        source.value,
                        now,
                        now,
                    ),
                )
        return TranscriptUpsertResult(TranscriptUpsertStatus.ACCEPTED)

    def delete_transcript(self, reference: JournalEventRef) -> TranscriptDeleteResult:
        connection = self._open_read_connection()
        if connection is None:
            return TranscriptDeleteResult(TranscriptDeleteStatus.NOT_FOUND)
        connection.close()

        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            self._ensure_schema(conn)
            cursor = conn.execute(
                """
                DELETE FROM transcript_overlays
                WHERE session_id = ? AND event_position = ?
                """,
                (reference.session_id, reference.event_position),
            )
        if cursor.rowcount == 0:
            return TranscriptDeleteResult(TranscriptDeleteStatus.NOT_FOUND)
        return TranscriptDeleteResult(TranscriptDeleteStatus.DELETED)

    def delete_session(self, session_id: str) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            connection.execute(
                "DELETE FROM transcript_overlays WHERE session_id = ?",
                (session_id,),
            )

    def rebuild(self) -> None:
        self._check_existing_schema_version()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)

    def count(self) -> int:
        connection = self._open_read_connection()
        if connection is None:
            return 0
        with closing(connection):
            if not _table_exists(connection, "transcript_overlays"):
                return 0
            row = connection.execute(
                "SELECT COUNT(*) FROM transcript_overlays"
            ).fetchone()
            return int(row[0]) if row else 0

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if _table_exists(connection, "transcript_overlay_meta"):
            self._check_schema_version(connection)
            return
        self._create_schema(connection)

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_overlay_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO transcript_overlay_meta (key, value)
            VALUES (?, ?)
            """,
            (_SCHEMA_VERSION_KEY, str(CURRENT_TRANSCRIPT_OVERLAY_SCHEMA_VERSION)),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_overlays (
                session_id TEXT NOT NULL,
                event_position INTEGER NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, event_position)
            )
            """
        )

    def _check_existing_schema_version(self) -> None:
        if not self._db_path.exists():
            return
        with closing(_connect_read_only(self._db_path)) as connection:
            self._check_schema_version(connection)

    def _check_schema_version(self, connection: sqlite3.Connection) -> None:
        if not _table_exists(connection, "transcript_overlay_meta"):
            return
        row = connection.execute(
            "SELECT value FROM transcript_overlay_meta WHERE key = ?",
            (_SCHEMA_VERSION_KEY,),
        ).fetchone()
        if row is None:
            return
        try:
            version = int(row[0])
        except ValueError as exc:
            raise TranscriptOverlaySchemaError(
                f"Invalid transcript overlay schema version: {row[0]!r}"
            ) from exc
        if version > CURRENT_TRANSCRIPT_OVERLAY_SCHEMA_VERSION:
            raise TranscriptOverlaySchemaError(
                "Transcript overlay database uses a newer schema version: "
                f"{version} > {CURRENT_TRANSCRIPT_OVERLAY_SCHEMA_VERSION}"
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


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _row_to_overlay(row: tuple[object, ...]) -> TranscriptOverlay:
    return TranscriptOverlay(
        reference=JournalEventRef(str(row[0]), int(row[1])),
        text=str(row[2]),
        source=TranscriptSource(str(row[3])),
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
