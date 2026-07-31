from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from jarvis.journal.events import (
    JournalEventRef,
    JSONValue,
    parse_journal_timestamp,
)
from jarvis.journal.store import JournalStore

CURRENT_HISTORY_CORPUS_SCHEMA_VERSION = 1
_CORPUS_FILE_NAME = "history_corpus.db"
_SCHEMA_VERSION_KEY = "schema_version"


class HistoryCorpusSchemaError(Exception):
    pass


@dataclass(frozen=True)
class HistoryCorpusEvent:
    reference: JournalEventRef
    timestamp: str
    timestamp_sort: float
    role: str
    source: str
    text: str
    media: tuple[str, ...]
    media_count: int
    transcript: str | None
    metadata: dict[str, JSONValue]


class HistoryCorpusRepository:
    def __init__(self, store: JournalStore, root: Path) -> None:
        self._store = store
        self._db_path = root / _CORPUS_FILE_NAME

    @property
    def db_path(self) -> Path:
        return self._db_path

    def rebuild(self) -> None:
        self._check_existing_schema_version()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection:
            connection.execute("BEGIN")
            try:
                self._drop_existing_schema(connection)
                self._create_schema(connection)
                self._insert_all_events(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def list_events(self) -> list[HistoryCorpusEvent]:
        if not self._db_path.exists():
            return []
        self._check_existing_schema_version()
        if not self._schema_exists():
            return []

        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    event_position,
                    timestamp,
                    timestamp_sort,
                    role,
                    source,
                    text,
                    media_json,
                    media_count,
                    transcript,
                    metadata_json
                FROM history_corpus_events
                ORDER BY timestamp_sort, session_id, event_position
                """
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _insert_all_events(self, connection: sqlite3.Connection) -> None:
        for session in self._store.list_sessions():
            replay = self._store.read_session(session.session_id)
            for record in replay.records:
                reference = record.reference
                event = record.event
                connection.execute(
                    """
                    INSERT INTO history_corpus_events (
                        session_id,
                        event_position,
                        timestamp,
                        timestamp_sort,
                        role,
                        source,
                        text,
                        media_json,
                        media_count,
                        transcript,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reference.session_id,
                        reference.event_position,
                        event.timestamp,
                        parse_journal_timestamp(event.timestamp).timestamp(),
                        event.role,
                        event.source,
                        event.text,
                        _json_dumps(list(event.media)),
                        len(event.media),
                        event.transcript,
                        _json_dumps(event.metadata),
                    ),
                )

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE history_corpus_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO history_corpus_meta (key, value)
            VALUES (?, ?)
            """,
            (_SCHEMA_VERSION_KEY, str(CURRENT_HISTORY_CORPUS_SCHEMA_VERSION)),
        )
        connection.execute(
            """
            CREATE TABLE history_corpus_events (
                session_id TEXT NOT NULL,
                event_position INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                timestamp_sort REAL NOT NULL,
                role TEXT NOT NULL,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                media_json TEXT NOT NULL,
                media_count INTEGER NOT NULL,
                transcript TEXT,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (session_id, event_position)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX history_corpus_events_sort_idx
            ON history_corpus_events (timestamp_sort, session_id, event_position)
            """
        )

    def _drop_existing_schema(self, connection: sqlite3.Connection) -> None:
        views = _schema_objects(connection, "view")
        tables = _schema_objects(connection, "table")
        for name in views:
            connection.execute(f"DROP VIEW IF EXISTS {_quote_sql_identifier(name)}")
        for name in tables:
            connection.execute(f"DROP TABLE IF EXISTS {_quote_sql_identifier(name)}")

    def _check_existing_schema_version(self) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection:
            if not _table_exists(connection, "history_corpus_meta"):
                return
            row = connection.execute(
                """
                SELECT value
                FROM history_corpus_meta
                WHERE key = ?
                """,
                (_SCHEMA_VERSION_KEY,),
            ).fetchone()
        if row is None:
            return
        try:
            version = int(row[0])
        except ValueError as exc:
            raise HistoryCorpusSchemaError(
                f"Invalid history corpus schema version: {row[0]!r}"
            ) from exc
        if version > CURRENT_HISTORY_CORPUS_SCHEMA_VERSION:
            raise HistoryCorpusSchemaError(
                "History corpus database uses a newer schema version: "
                f"{version} > {CURRENT_HISTORY_CORPUS_SCHEMA_VERSION}"
            )

    def _schema_exists(self) -> bool:
        with closing(sqlite3.connect(self._db_path)) as connection:
            return _table_exists(connection, "history_corpus_events")

    @staticmethod
    def _row_to_event(row: sqlite3.Row | tuple[object, ...]) -> HistoryCorpusEvent:
        media = _json_load_list(row[7], "media_json")
        metadata = _json_load_object(row[10], "metadata_json")
        return HistoryCorpusEvent(
            reference=JournalEventRef(str(row[0]), int(row[1])),
            timestamp=str(row[2]),
            timestamp_sort=float(row[3]),
            role=str(row[4]),
            source=str(row[5]),
            text=str(row[6]),
            media=tuple(media),
            media_count=int(row[8]),
            transcript=None if row[9] is None else str(row[9]),
            metadata=metadata,
        )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (name,),
    ).fetchone()
    return row is not None


def _schema_objects(connection: sqlite3.Connection, kind: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = ? AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """,
        (kind,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _quote_sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _json_dumps(value: JSONValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_load_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, str):
        raise HistoryCorpusSchemaError(f"{field_name} must be stored as JSON text")
    parsed = json.loads(value)
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise HistoryCorpusSchemaError(f"{field_name} must be a JSON string list")
    return list(parsed)


def _json_load_object(value: object, field_name: str) -> dict[str, JSONValue]:
    if not isinstance(value, str):
        raise HistoryCorpusSchemaError(f"{field_name} must be stored as JSON text")
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise HistoryCorpusSchemaError(f"{field_name} must be a JSON object")
    return dict(parsed)
