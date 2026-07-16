from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from jarvis.journal.events import parse_journal_timestamp
from jarvis.journal.store import JournalStore

_INDEX_FILE_NAME = "index.db"
_QUERY_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class JournalSearchHit:
    session_id: str
    timestamp: str
    event_position: int
    snippet: str


class JournalSearchIndex:
    def __init__(self, store: JournalStore, root: Path) -> None:
        self._store = store
        self._db_path = root / _INDEX_FILE_NAME

    def rebuild(self) -> None:
        with closing(self._connect()) as connection, connection:
            self._drop_schema(connection)
            self._create_schema(connection)
            for session in self._store.list_sessions():
                self._index_session(connection, session.session_id)

    def update_session(self, session_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            self._create_schema(connection)
            connection.execute(
                "DELETE FROM journal_search_events WHERE session_id = ?",
                (session_id,),
            )
            self._index_session(connection, session_id)

    def search(
        self,
        query: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[JournalSearchHit]:
        if limit < 1:
            raise ValueError("limit must be positive")

        match_query = _to_prefix_match_query(query)
        where_parts: list[str] = []
        parameters: list[str | int | float] = []
        if match_query:
            where_parts.append("journal_search_events MATCH ?")
            parameters.append(match_query)
        _append_date_filter(where_parts, parameters, "date_from", date_from)
        _append_date_filter(where_parts, parameters, "date_to", date_to)

        where_sql = ""
        if where_parts:
            where_sql = "WHERE " + " AND ".join(where_parts)

        sql = f"""
            SELECT
                session_id,
                timestamp,
                event_position,
                CASE
                    WHEN ? THEN snippet(journal_search_events, 5, '[', ']', '...', 24)
                    ELSE text
                END
            FROM journal_search_events
            {where_sql}
            ORDER BY timestamp_sort, session_id, event_position
            LIMIT ?
        """
        parameters = [1 if match_query else 0, *parameters, limit]

        if not self._db_path.exists():
            return []
        with closing(self._connect_readonly()) as connection:
            if not self._schema_exists(connection):
                return []
            rows = connection.execute(sql, parameters).fetchall()

        return [
            JournalSearchHit(
                session_id=row[0],
                timestamp=row[1],
                event_position=row[2],
                snippet=row[3],
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self._db_path)

    def _connect_readonly(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{self._db_path.resolve().as_uri()}?mode=ro", uri=True)

    def _index_session(self, connection: sqlite3.Connection, session_id: str) -> None:
        replay = self._store.read_session(session_id)
        for position, event in enumerate(replay.events):
            if event.role != "assistant" or not event.text:
                continue
            timestamp = parse_journal_timestamp(event.timestamp)
            connection.execute(
                """
                INSERT INTO journal_search_events (
                    session_id,
                    timestamp,
                    timestamp_sort,
                    event_date,
                    event_position,
                    text
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.session_id,
                    event.timestamp,
                    timestamp.timestamp(),
                    timestamp.date().isoformat(),
                    position,
                    event.text,
                ),
            )

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS journal_search_events USING fts5(
                session_id UNINDEXED,
                timestamp UNINDEXED,
                timestamp_sort UNINDEXED,
                event_date UNINDEXED,
                event_position UNINDEXED,
                text,
                tokenize = 'unicode61',
                prefix = '1 2 3 4 5 6 7 8 9 10'
            )
            """
        )

    def _drop_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute("DROP TABLE IF EXISTS journal_search_events")

    def _schema_exists(self, connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'journal_search_events'
            """
        ).fetchone()
        return row is not None


def _to_prefix_match_query(query: str) -> str:
    tokens = _QUERY_TOKEN_PATTERN.findall(query.casefold())
    return " AND ".join(f"{token}*" for token in tokens)


def _append_date_filter(
    where_parts: list[str],
    parameters: list[str | int | float],
    field: str,
    value: str | None,
) -> None:
    if value is None:
        return

    bound = _parse_date_bound(value)
    operator = ">=" if field == "date_from" else "<="
    column = "timestamp_sort" if isinstance(bound, datetime) else "event_date"
    where_parts.append(f"{column} {operator} ?")
    if isinstance(bound, datetime):
        parameters.append(bound.timestamp())
    else:
        parameters.append(bound.isoformat())


def _parse_date_bound(value: str) -> date | datetime:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return parse_journal_timestamp(value)
