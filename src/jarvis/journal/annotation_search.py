"""Lexical retrieval projection over session annotations (task v1.8.0-23).

A rebuildable derived FTS index over the text of session annotations, physically
separate from the event corpus FTS so an annotation row can never be mistaken
for - or replace - a raw event. Identity is the ``annotation_id``; callers
hydrate the full annotation (target, source, author, status) from the overlay
store, so the index carries only what search needs.

Only ``ACTIVE`` annotations are indexed: a ``DISMISSED`` annotation is hidden
from retrieval without being deleted (story-v1.8.0 decision 5). Re-projection of
a now-dismissed annotation therefore removes its row, and re-activating it adds
the row back.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from jarvis.journal.annotation import Annotation, AnnotationStatus
from jarvis.journal.events import parse_journal_timestamp


class AnnotationListSource(Protocol):
    """Enumerates every stored annotation for a full projection rebuild.

    ``AnnotationOverlayRepository`` satisfies this structurally.
    """

    def list_all_annotations(self) -> tuple[Annotation, ...]: ...


ANNOTATION_SEARCH_DB_NAME = "annotation_search_index.db"
ANNOTATION_SEARCH_MAX_RESULTS = 500
CURRENT_ANNOTATION_SEARCH_SCHEMA_VERSION = 1
_SCHEMA_VERSION_KEY = "schema_version"
_QUERY_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class AnnotationSearchStatus(Enum):
    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"
    INVALID_LIMIT = "invalid_limit"
    TOO_MANY_RESULTS = "too_many_results"


@dataclass(frozen=True)
class AnnotationSearchRequest:
    query: str = ""
    term_groups: tuple[tuple[str, ...], ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    session_ids: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    limit: int = 50


@dataclass(frozen=True)
class AnnotationSearchHit:
    annotation_id: str
    session_id: str
    timestamp: str
    source: str
    snippet: str
    score: float
    order_index: int


@dataclass(frozen=True)
class AnnotationSearchResult:
    status: AnnotationSearchStatus
    hits: tuple[AnnotationSearchHit, ...] = ()
    max_results: int = ANNOTATION_SEARCH_MAX_RESULTS


class AnnotationSearchIndex:
    """SQLite FTS5 projection over annotation text, keyed by ``annotation_id``.

    Implements the ``AnnotationDerivedProjection`` shape consumed by
    ``HistoryProjectionLifecycle``: ``startup_rebuild`` rebuilds from the overlay
    store, ``reproject_annotation``/``delete_annotation_projection`` maintain one
    annotation on change, and ``delete_session_projection`` clears a session on
    deletion.
    """

    name = "annotation_search"

    def __init__(self, repository: AnnotationListSource, root: Path) -> None:
        self._repository = repository
        self._db_path = root / ANNOTATION_SEARCH_DB_NAME

    @property
    def db_path(self) -> Path:
        return self._db_path

    def startup_rebuild(self) -> None:
        self.rebuild()

    def rebuild(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection:
            connection.execute("BEGIN")
            try:
                _drop_schema(connection)
                _create_schema(connection)
                for annotation in self._repository.list_all_annotations():
                    _insert_annotation(connection, annotation)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def reproject_annotation(self, annotation: Annotation) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            _ensure_schema(connection)
            _delete_annotation(connection, annotation.annotation_id)
            _insert_annotation(connection, annotation)

    def delete_annotation_projection(self, annotation_id: str) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            _ensure_schema(connection)
            _delete_annotation(connection, annotation_id)

    def delete_session_projection(self, session_id: str) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            _ensure_schema(connection)
            connection.execute(
                "DELETE FROM annotation_fts WHERE session_id = ?", (session_id,)
            )

    def search(self, request: AnnotationSearchRequest) -> AnnotationSearchResult:
        if request.limit < 1:
            return AnnotationSearchResult(AnnotationSearchStatus.INVALID_LIMIT)
        if request.limit > ANNOTATION_SEARCH_MAX_RESULTS:
            return AnnotationSearchResult(AnnotationSearchStatus.TOO_MANY_RESULTS)
        if not self._db_path.exists():
            return AnnotationSearchResult(AnnotationSearchStatus.UNAVAILABLE)
        with closing(_connect_read_only(self._db_path)) as connection:
            if not _table_exists(connection, "annotation_fts"):
                return AnnotationSearchResult(AnnotationSearchStatus.UNAVAILABLE)
            rows = connection.execute(
                _search_sql(request), _search_parameters(request)
            ).fetchall()
        hits = tuple(
            AnnotationSearchHit(
                annotation_id=str(row[0]),
                session_id=str(row[1]),
                timestamp=str(row[2]),
                source=str(row[3]),
                snippet=str(row[4]),
                score=float(row[5]),
                order_index=index,
            )
            for index, row in enumerate(rows)
        )
        return AnnotationSearchResult(AnnotationSearchStatus.ACCEPTED, hits)


def _insert_annotation(connection: sqlite3.Connection, annotation: Annotation) -> None:
    if annotation.status is not AnnotationStatus.ACTIVE or not annotation.text.strip():
        return
    timestamp = parse_journal_timestamp(annotation.created_at)
    connection.execute(
        """
        INSERT INTO annotation_fts (
            annotation_id, session_id, timestamp, timestamp_sort, event_date,
            source, text
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            annotation.annotation_id,
            annotation.target.session_id,
            annotation.created_at,
            timestamp.timestamp(),
            timestamp.date().isoformat(),
            annotation.source.value,
            annotation.text,
        ),
    )


def _delete_annotation(connection: sqlite3.Connection, annotation_id: str) -> None:
    connection.execute(
        "DELETE FROM annotation_fts WHERE annotation_id = ?", (annotation_id,)
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE annotation_search_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO annotation_search_meta (key, value) VALUES (?, ?)",
        (_SCHEMA_VERSION_KEY, str(CURRENT_ANNOTATION_SEARCH_SCHEMA_VERSION)),
    )
    connection.execute(
        """
        CREATE VIRTUAL TABLE annotation_fts USING fts5(
            annotation_id UNINDEXED,
            session_id UNINDEXED,
            timestamp UNINDEXED,
            timestamp_sort UNINDEXED,
            event_date UNINDEXED,
            source UNINDEXED,
            text,
            tokenize = 'unicode61',
            prefix = '1 2 3 4 5 6 7 8 9 10'
        )
        """
    )


def _drop_schema(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS annotation_fts")
    connection.execute("DROP TABLE IF EXISTS annotation_search_meta")


def _ensure_schema(connection: sqlite3.Connection) -> None:
    if _table_exists(connection, "annotation_fts"):
        return
    _create_schema(connection)


def _search_sql(request: AnnotationSearchRequest) -> str:
    where_parts: list[str] = []
    match_query = _match_query(request)
    if match_query:
        where_parts.append("annotation_fts MATCH ?")
    if request.date_from is not None:
        where_parts.append("event_date >= ?")
    if request.date_to is not None:
        where_parts.append("event_date <= ?")
    if request.session_ids:
        placeholders = ", ".join("?" for _ in request.session_ids)
        where_parts.append(f"session_id IN ({placeholders})")
    if request.sources:
        placeholders = ", ".join("?" for _ in request.sources)
        where_parts.append(f"source IN ({placeholders})")
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    snippet_source = "1" if match_query else "0"
    return f"""
        SELECT
            annotation_id,
            session_id,
            timestamp,
            source,
            CASE
                WHEN {snippet_source} THEN
                    snippet(annotation_fts, 6, '[', ']', '...', 24)
                ELSE text
            END,
            bm25(annotation_fts)
        FROM annotation_fts
        {where_sql}
        ORDER BY bm25(annotation_fts), timestamp_sort, annotation_id
        LIMIT ?
    """


def _search_parameters(request: AnnotationSearchRequest) -> list[str | int | float]:
    parameters: list[str | int | float] = []
    match_query = _match_query(request)
    if match_query:
        parameters.append(match_query)
    if request.date_from is not None:
        parameters.append(request.date_from)
    if request.date_to is not None:
        parameters.append(request.date_to)
    parameters.extend(request.session_ids)
    parameters.extend(request.sources)
    parameters.append(request.limit)
    return parameters


def _match_query(request: AnnotationSearchRequest) -> str:
    if not request.term_groups:
        tokens = _QUERY_TOKEN_PATTERN.findall(request.query.casefold())
        return " AND ".join(f"{token}*" for token in tokens)
    groups: list[str] = []
    for group in request.term_groups:
        tokens = tuple(
            dict.fromkeys(
                token
                for term in group
                for token in _QUERY_TOKEN_PATTERN.findall(term.casefold())
            )
        )
        if not tokens:
            continue
        if len(tokens) == 1:
            groups.append(f"{tokens[0]}*")
        else:
            groups.append("(" + " OR ".join(f"{token}*" for token in tokens) + ")")
    return " AND ".join(groups)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
