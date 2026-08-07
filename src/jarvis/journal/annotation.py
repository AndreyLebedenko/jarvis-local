"""Annotation overlay store: bounded, source-grounded session annotations.

Annotations are derived, auditable model or user notes that stay linked to
their source material - a whole session or an explicit contiguous event range -
without ever rewriting the raw JSONL journal. They help retrieval and review
but never replace source events (story-v1.8.0 design decision 5).

This module owns only storage: schema, source references, size/count/metadata
caps, read/write/delete, session deletion, and rebuild health. Model
generation, UI controls, and retrieval-projection integration are separate
task cards and are deliberately not implemented here.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from jarvis.journal.events import JournalEventRef, JSONValue
from jarvis.journal.transcript import EventReferenceResolver

CURRENT_ANNOTATION_OVERLAY_SCHEMA_VERSION = 1
ANNOTATION_OVERLAY_DB_NAME = "annotation_overlays.db"
ANNOTATION_MAX_TEXT_LENGTH = 20_000
ANNOTATION_MAX_AUTHOR_LENGTH = 200
ANNOTATION_MAX_PER_SESSION = 200
ANNOTATION_MAX_METADATA_ENTRIES = 32
ANNOTATION_MAX_METADATA_SERIALIZED_LENGTH = 4_000
_SCHEMA_VERSION_KEY = "schema_version"


class AnnotationOverlaySchemaError(Exception):
    pass


class AnnotationSource(Enum):
    """How the stored annotation text entered the store.

    Mirrors ``TranscriptSource``: ``GENERATED`` is model-produced text (the
    task-v1.8.0-22 generator). ``EDITED`` covers any human change through the
    Journal surface, from a light correction to a full rewrite; there is no
    separate human-authored source (owner decision, 2026-08-06).
    """

    GENERATED = "generated"
    EDITED = "edited"


class AnnotationStatus(Enum):
    """Whether the annotation currently participates as auditable data.

    ``ACTIVE`` annotations are the normal state. ``DISMISSED`` marks an
    annotation a user chose to set aside without deleting it, preserving the
    audit trail; nothing in this card produces that transition automatically -
    it exists so a later UI can hide an annotation without destroying it.
    """

    ACTIVE = "active"
    DISMISSED = "dismissed"


class AnnotationReadStatus(Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"


class AnnotationWriteStatus(Enum):
    ACCEPTED = "accepted"
    UNKNOWN_REFERENCE = "unknown_reference"
    INVALID_TARGET = "invalid_target"
    TEXT_EMPTY = "text_empty"
    TEXT_TOO_LONG = "text_too_long"
    AUTHOR_EMPTY = "author_empty"
    AUTHOR_TOO_LONG = "author_too_long"
    INVALID_SOURCE = "invalid_source"
    INVALID_STATUS = "invalid_status"
    METADATA_INVALID = "metadata_invalid"
    METADATA_TOO_LARGE = "metadata_too_large"
    TOO_MANY_ANNOTATIONS = "too_many_annotations"
    UNKNOWN_ANNOTATION = "unknown_annotation"


class AnnotationDeleteStatus(Enum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class AnnotationTarget:
    """A session-wide or explicit event-range anchor for an annotation.

    ``start_position`` and ``end_position`` are both ``None`` for a
    whole-session annotation, or both set for an inclusive event range
    (``start_position <= end_position``). One set and the other ``None`` is an
    invalid target.
    """

    session_id: str
    start_position: int | None = None
    end_position: int | None = None

    @property
    def is_whole_session(self) -> bool:
        return self.start_position is None and self.end_position is None


@dataclass(frozen=True)
class Annotation:
    annotation_id: str
    target: AnnotationTarget
    text: str
    author: str
    source: AnnotationSource
    status: AnnotationStatus
    created_at: str
    updated_at: str
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class AnnotationRead:
    status: AnnotationReadStatus
    annotation: Annotation | None = None

    @property
    def found(self) -> bool:
        return self.status is AnnotationReadStatus.FOUND


@dataclass(frozen=True)
class AnnotationWriteResult:
    status: AnnotationWriteStatus
    annotation_id: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status is AnnotationWriteStatus.ACCEPTED


@dataclass(frozen=True)
class AnnotationDeleteResult:
    status: AnnotationDeleteStatus


@dataclass(frozen=True)
class AnnotationOverlayChanged:
    """Published when an annotation is added, edited, or removed.

    Mirrors ``TranscriptOverlayChanged``: overlay writers (the API edit path and
    the task-22 generator) publish it so the history projection lifecycle can
    reproject just this annotation's derived lexical and semantic rows, without
    the writers knowing about projections. ``annotation_id`` identifies the row
    to reproject; ``session_id`` is carried for filtering and diagnostics. A
    deleted annotation still publishes it - the reprojection then finds the row
    gone and clears the derived rows instead of re-indexing.
    """

    session_id: str
    annotation_id: str


class AnnotationOverlayRepository:
    def __init__(self, root: Path, references: EventReferenceResolver) -> None:
        self._db_path = root / ANNOTATION_OVERLAY_DB_NAME
        self._references = references

    @property
    def db_path(self) -> Path:
        return self._db_path

    def add_annotation(
        self,
        target: AnnotationTarget,
        text: str,
        author: str,
        source: AnnotationSource,
        status: AnnotationStatus = AnnotationStatus.ACTIVE,
        metadata: dict[str, JSONValue] | None = None,
    ) -> AnnotationWriteResult:
        content_status = _validate_content(text, author, source, status)
        if content_status is not None:
            return AnnotationWriteResult(content_status)
        metadata_json, metadata_status = _encode_metadata(metadata)
        if metadata_status is not None:
            return AnnotationWriteResult(metadata_status)
        target_status = self._validate_target(target)
        if target_status is not None:
            return AnnotationWriteResult(target_status)

        now = _utc_now_iso()
        annotation_id = uuid.uuid4().hex
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            count = connection.execute(
                "SELECT COUNT(*) FROM annotation_overlays WHERE session_id = ?",
                (target.session_id,),
            ).fetchone()[0]
            if count >= ANNOTATION_MAX_PER_SESSION:
                return AnnotationWriteResult(AnnotationWriteStatus.TOO_MANY_ANNOTATIONS)
            connection.execute(
                """
                INSERT INTO annotation_overlays
                    (annotation_id, session_id, start_position, end_position,
                     text, author, source, status, metadata,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    annotation_id,
                    target.session_id,
                    target.start_position,
                    target.end_position,
                    text,
                    author,
                    source.value,
                    status.value,
                    metadata_json,
                    now,
                    now,
                ),
            )
        return AnnotationWriteResult(AnnotationWriteStatus.ACCEPTED, annotation_id)

    def update_annotation(
        self,
        annotation_id: str,
        *,
        text: str | None = None,
        author: str | None = None,
        source: AnnotationSource | None = None,
        status: AnnotationStatus | None = None,
        metadata: dict[str, JSONValue] | None = None,
    ) -> AnnotationWriteResult:
        existing = self.read_annotation(annotation_id)
        if not existing.found or existing.annotation is None:
            return AnnotationWriteResult(AnnotationWriteStatus.UNKNOWN_ANNOTATION)
        current = existing.annotation
        new_text = current.text if text is None else text
        new_author = current.author if author is None else author
        new_source = current.source if source is None else source
        new_status = current.status if status is None else status
        content_status = _validate_content(new_text, new_author, new_source, new_status)
        if content_status is not None:
            return AnnotationWriteResult(content_status)
        new_metadata = current.metadata if metadata is None else metadata
        metadata_json, metadata_status = _encode_metadata(new_metadata)
        if metadata_status is not None:
            return AnnotationWriteResult(metadata_status)

        now = _utc_now_iso()
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                UPDATE annotation_overlays
                SET text = ?, author = ?, source = ?, status = ?,
                    metadata = ?, updated_at = ?
                WHERE annotation_id = ?
                """,
                (
                    new_text,
                    new_author,
                    new_source.value,
                    new_status.value,
                    metadata_json,
                    now,
                    annotation_id,
                ),
            )
        return AnnotationWriteResult(AnnotationWriteStatus.ACCEPTED, annotation_id)

    def read_annotation(self, annotation_id: str) -> AnnotationRead:
        connection = self._open_read_connection()
        if connection is None:
            return AnnotationRead(AnnotationReadStatus.NOT_FOUND)
        with closing(connection):
            if not _table_exists(connection, "annotation_overlays"):
                return AnnotationRead(AnnotationReadStatus.NOT_FOUND)
            row = connection.execute(
                f"SELECT {_ANNOTATION_COLUMNS} FROM annotation_overlays "
                "WHERE annotation_id = ?",
                (annotation_id,),
            ).fetchone()
        if row is None:
            return AnnotationRead(AnnotationReadStatus.NOT_FOUND)
        return AnnotationRead(AnnotationReadStatus.FOUND, _row_to_annotation(row))

    def list_all_annotations(self) -> tuple[Annotation, ...]:
        """Every annotation across all sessions, in insertion order.

        The derived retrieval projections (task v1.8.0-23) enumerate the store
        through this to rebuild their lexical and semantic rows from scratch.
        """

        connection = self._open_read_connection()
        if connection is None:
            return ()
        with closing(connection):
            if not _table_exists(connection, "annotation_overlays"):
                return ()
            rows = connection.execute(
                f"SELECT {_ANNOTATION_COLUMNS} FROM annotation_overlays ORDER BY rowid"
            ).fetchall()
        return tuple(_row_to_annotation(row) for row in rows)

    def read_session_annotations(self, session_id: str) -> tuple[Annotation, ...]:
        connection = self._open_read_connection()
        if connection is None:
            return ()
        with closing(connection):
            if not _table_exists(connection, "annotation_overlays"):
                return ()
            rows = connection.execute(
                f"SELECT {_ANNOTATION_COLUMNS} FROM annotation_overlays "
                "WHERE session_id = ? ORDER BY rowid",
                (session_id,),
            ).fetchall()
        return tuple(_row_to_annotation(row) for row in rows)

    def delete_annotation(self, annotation_id: str) -> AnnotationDeleteResult:
        if not self._db_path.exists():
            return AnnotationDeleteResult(AnnotationDeleteStatus.NOT_FOUND)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                "DELETE FROM annotation_overlays WHERE annotation_id = ?",
                (annotation_id,),
            )
        if cursor.rowcount == 0:
            return AnnotationDeleteResult(AnnotationDeleteStatus.NOT_FOUND)
        return AnnotationDeleteResult(AnnotationDeleteStatus.DELETED)

    def delete_session(self, session_id: str) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            connection.execute(
                "DELETE FROM annotation_overlays WHERE session_id = ?",
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
            if not _table_exists(connection, "annotation_overlays"):
                return 0
            row = connection.execute(
                "SELECT COUNT(*) FROM annotation_overlays"
            ).fetchone()
            return int(row[0]) if row else 0

    def _validate_target(
        self, target: AnnotationTarget
    ) -> AnnotationWriteStatus | None:
        start, end = target.start_position, target.end_position
        if (start is None) != (end is None):
            return AnnotationWriteStatus.INVALID_TARGET
        if (
            start is not None
            and end is not None
            and (_is_bad_position(start) or _is_bad_position(end) or start > end)
        ):
            return AnnotationWriteStatus.INVALID_TARGET
        if target.is_whole_session:
            probe = _build_reference(target.session_id, 0)
        else:
            probe = _build_reference(target.session_id, end)
        if probe is None:
            return AnnotationWriteStatus.UNKNOWN_REFERENCE
        if not self._references.event_exists(probe):
            return AnnotationWriteStatus.UNKNOWN_REFERENCE
        if not target.is_whole_session and start is not None and start > 0:
            start_ref = _build_reference(target.session_id, start)
            if start_ref is None or not self._references.event_exists(start_ref):
                return AnnotationWriteStatus.UNKNOWN_REFERENCE
        return None

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if _table_exists(connection, "annotation_overlay_meta"):
            self._check_schema_version(connection)
            return
        self._create_schema(connection)

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS annotation_overlay_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO annotation_overlay_meta (key, value)
            VALUES (?, ?)
            """,
            (_SCHEMA_VERSION_KEY, str(CURRENT_ANNOTATION_OVERLAY_SCHEMA_VERSION)),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS annotation_overlays (
                annotation_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                start_position INTEGER,
                end_position INTEGER,
                text TEXT NOT NULL,
                author TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS annotation_overlays_session_idx "
            "ON annotation_overlays (session_id)"
        )

    def _check_existing_schema_version(self) -> None:
        if not self._db_path.exists():
            return
        with closing(_connect_read_only(self._db_path)) as connection:
            self._check_schema_version(connection)

    def _check_schema_version(self, connection: sqlite3.Connection) -> None:
        if not _table_exists(connection, "annotation_overlay_meta"):
            return
        row = connection.execute(
            "SELECT value FROM annotation_overlay_meta WHERE key = ?",
            (_SCHEMA_VERSION_KEY,),
        ).fetchone()
        if row is None:
            return
        try:
            version = int(row[0])
        except ValueError as exc:
            raise AnnotationOverlaySchemaError(
                f"Invalid annotation overlay schema version: {row[0]!r}"
            ) from exc
        if version > CURRENT_ANNOTATION_OVERLAY_SCHEMA_VERSION:
            raise AnnotationOverlaySchemaError(
                "Annotation overlay database uses a newer schema version: "
                f"{version} > {CURRENT_ANNOTATION_OVERLAY_SCHEMA_VERSION}"
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


_ANNOTATION_COLUMNS = (
    "annotation_id, session_id, start_position, end_position, text, author, "
    "source, status, metadata, created_at, updated_at"
)


def _validate_content(
    text: str,
    author: str,
    source: AnnotationSource,
    status: AnnotationStatus,
) -> AnnotationWriteStatus | None:
    if not text:
        return AnnotationWriteStatus.TEXT_EMPTY
    if len(text) > ANNOTATION_MAX_TEXT_LENGTH:
        return AnnotationWriteStatus.TEXT_TOO_LONG
    if not author:
        return AnnotationWriteStatus.AUTHOR_EMPTY
    if len(author) > ANNOTATION_MAX_AUTHOR_LENGTH:
        return AnnotationWriteStatus.AUTHOR_TOO_LONG
    if not isinstance(source, AnnotationSource):
        return AnnotationWriteStatus.INVALID_SOURCE
    if not isinstance(status, AnnotationStatus):
        return AnnotationWriteStatus.INVALID_STATUS
    return None


def _encode_metadata(
    metadata: dict[str, JSONValue] | None,
) -> tuple[str, AnnotationWriteStatus | None]:
    if metadata is None:
        return "{}", None
    if not isinstance(metadata, dict) or any(
        not isinstance(key, str) for key in metadata
    ):
        return "", AnnotationWriteStatus.METADATA_INVALID
    if len(metadata) > ANNOTATION_MAX_METADATA_ENTRIES:
        return "", AnnotationWriteStatus.METADATA_TOO_LARGE
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return "", AnnotationWriteStatus.METADATA_INVALID
    if len(encoded) > ANNOTATION_MAX_METADATA_SERIALIZED_LENGTH:
        return "", AnnotationWriteStatus.METADATA_TOO_LARGE
    return encoded, None


def _is_bad_position(value: int) -> bool:
    return isinstance(value, bool) or not isinstance(value, int) or value < 0


def _build_reference(session_id: str, position: int | None) -> JournalEventRef | None:
    if position is None:
        return None
    try:
        return JournalEventRef(session_id, position)
    except ValueError:
        return None


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _row_to_annotation(row: tuple[object, ...]) -> Annotation:
    metadata = json.loads(str(row[8]))
    return Annotation(
        annotation_id=str(row[0]),
        target=AnnotationTarget(
            session_id=str(row[1]),
            start_position=None if row[2] is None else int(row[2]),
            end_position=None if row[3] is None else int(row[3]),
        ),
        text=str(row[4]),
        author=str(row[5]),
        source=AnnotationSource(str(row[6])),
        status=AnnotationStatus(str(row[7])),
        metadata=metadata,
        created_at=str(row[9]),
        updated_at=str(row[10]),
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
