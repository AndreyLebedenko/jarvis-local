"""Rebuildable source-grounded semantic history projection."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import httpx

from jarvis.core.config import BackendSettings, HistorySemanticSettings
from jarvis.journal.corpus import (
    HISTORY_SEARCH_MAX_RESULTS,
    HistoryCorpusEvent,
    HistoryCorpusRepository,
)
from jarvis.journal.events import JournalEventRecord, JournalEventRef
from jarvis.journal.lifecycle import (
    HistoryProjectionStatus,
    SemanticProjectionBackendIdentity,
    SemanticProjectionState,
)

CURRENT_SEMANTIC_PROJECTION_SCHEMA_VERSION = 1
SEMANTIC_PROJECTION_DB_NAME = "semantic_index.db"
SEMANTIC_MAX_RESULTS = HISTORY_SEARCH_MAX_RESULTS

_SCHEMA_VERSION_KEY = "schema_version"
_MODEL_KEY = "model"
_DIMENSION_KEY = "dimension"
_QUERY_PREFIX_KEY = "query_prefix"
_PASSAGE_PREFIX_KEY = "passage_prefix"


class SemanticProjectionSchemaError(Exception):
    """Raised when a semantic index cannot be safely interpreted."""


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...


class OllamaEmbeddingProvider:
    """Small synchronous seam for Ollama's local embedding endpoint."""

    def __init__(
        self,
        settings: BackendSettings,
        semantic_settings: HistorySemanticSettings,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._semantic_settings = semantic_settings
        self._client = client

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        if self._client is not None:
            return self._embed_with_client(self._client, texts)
        timeout = httpx.Timeout(10.0, read=self._settings.read_timeout_seconds)
        with httpx.Client(base_url=self._settings.endpoint, timeout=timeout) as client:
            return self._embed_with_client(client, texts)

    def _embed_with_client(
        self, client: httpx.Client, texts: Sequence[str]
    ) -> list[tuple[float, ...]]:
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            response = client.post(
                f"{self._settings.endpoint.rstrip('/')}/api/embeddings",
                json={"model": self._semantic_settings.model, "prompt": text},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Ollama embedding response must be an object")
            raw_vector = payload.get("embedding")
            if not isinstance(raw_vector, list):
                raise ValueError("Ollama embedding response has no embedding list")
            if any(
                not isinstance(value, int | float) or isinstance(value, bool)
                for value in raw_vector
            ):
                raise ValueError("Ollama embedding vector must contain numbers")
            vectors.append(tuple(float(value) for value in raw_vector))
        return vectors


@dataclass(frozen=True)
class SemanticPassage:
    passage_id: str
    reference: JournalEventRef
    timestamp: str
    role: str
    source: str
    text: str


@dataclass(frozen=True)
class SemanticCandidateQuery:
    query: str
    limit: int = SEMANTIC_MAX_RESULTS
    session_ids: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    roles: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticCandidate:
    passage_id: str
    reference: JournalEventRef
    score: float


class SemanticCandidateStatus(Enum):
    ACCEPTED = "accepted"
    INVALID_QUERY = "invalid_query"
    TOO_MANY_RESULTS = "too_many_results"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SemanticCandidateResult:
    status: SemanticCandidateStatus
    candidates: tuple[SemanticCandidate, ...] = ()
    max_results: int = SEMANTIC_MAX_RESULTS


class SemanticPassageIndex:
    """SQLite-backed semantic passage and vector projection.

    The index stores one passage per eligible source event. Passage identity is
    derived only from ``JournalEventRef``, so a rebuild cannot create a second
    identity for the same source event. Candidate results expose references and
    scores only; callers hydrate source text through the corpus repository.
    """

    name = "semantic"

    def __init__(
        self,
        repository: HistoryCorpusRepository,
        root: Path,
        settings: HistorySemanticSettings,
        embedder: EmbeddingProvider,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._db_path = root / SEMANTIC_PROJECTION_DB_NAME
        self._settings = settings
        self._embedder = embedder
        self._logger = logger or logging.getLogger(__name__)
        self._runtime_error: str | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def configured_backend(self) -> SemanticProjectionBackendIdentity:
        return SemanticProjectionBackendIdentity(
            model=self._settings.model,
            dimension=self._settings.dimension,
            query_prefix=self._settings.query_prefix,
            passage_prefix=self._settings.passage_prefix,
        )

    def state(self) -> SemanticProjectionState:
        stored = self._read_backend_identity()
        if not self._settings.enabled:
            return SemanticProjectionState(
                HistoryProjectionStatus.UNAVAILABLE,
                configured_backend=self.configured_backend,
                stored_backend=stored,
                last_error="semantic projection is disabled",
            )
        if stored is None:
            return SemanticProjectionState(
                (
                    HistoryProjectionStatus.UNAVAILABLE
                    if self._runtime_error is not None
                    else HistoryProjectionStatus.UNBUILT
                ),
                configured_backend=self.configured_backend,
                last_error=self._runtime_error,
            )
        if stored != self.configured_backend:
            return SemanticProjectionState(
                HistoryProjectionStatus.UNAVAILABLE,
                configured_backend=self.configured_backend,
                stored_backend=stored,
                last_error="stored semantic backend does not match configuration",
            )
        if self._runtime_error is not None:
            return SemanticProjectionState(
                HistoryProjectionStatus.UNAVAILABLE,
                configured_backend=self.configured_backend,
                stored_backend=stored,
                last_error=self._runtime_error,
            )
        return SemanticProjectionState(
            HistoryProjectionStatus.ENABLED,
            configured_backend=self.configured_backend,
            stored_backend=stored,
            passage_count=self._passage_count(),
        )

    def rebuild_if_backend_changed(self) -> None:
        if not self._settings.enabled:
            return
        stored = self._read_backend_identity()
        if stored == self.configured_backend:
            self._runtime_error = None
            return
        self.rebuild()

    def rebuild(self) -> None:
        if not self._settings.enabled:
            return
        try:
            self._check_existing_schema()
            passages = tuple(
                passage
                for event in self._repository.list_events()
                if (passage := _passage_from_corpus_event(event)) is not None
            )
            vectors = self._embedder.embed(
                [self._settings.passage_prefix + passage.text for passage in passages]
            )
            _validate_vectors(vectors, len(passages), self._settings.dimension)
            self._replace_index(passages, vectors)
        except SemanticProjectionSchemaError:
            raise
        except Exception as exc:
            self._mark_unavailable(exc, "semantic projection rebuild failed")
            return
        self._runtime_error = None

    def project_event(self, record: JournalEventRecord) -> None:
        if self.state().status is not HistoryProjectionStatus.ENABLED:
            return
        passage = _passage_from_record(record)
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._db_path)) as connection:
                connection.execute("BEGIN")
                self._delete_event(connection, record.reference)
                if passage is not None:
                    vectors = self._embedder.embed(
                        [self._settings.passage_prefix + passage.text]
                    )
                    _validate_vectors(vectors, 1, self._settings.dimension)
                    self._insert_passage(connection, passage, vectors[0])
                connection.commit()
        except SemanticProjectionSchemaError:
            raise
        except Exception as exc:
            self._mark_unavailable(exc, "semantic projection update failed")

    def delete_session_projection(self, session_id: str) -> None:
        if not self._db_path.exists():
            return
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            connection.execute(
                "DELETE FROM semantic_passages WHERE session_id = ?", (session_id,)
            )

    def list_passages(self) -> tuple[SemanticPassage, ...]:
        if not self._db_path.exists():
            return ()
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                """
                SELECT passage_id, session_id, event_position, timestamp, role,
                       source, text
                FROM semantic_passages
                ORDER BY passage_id
                """
            ).fetchall()
        return tuple(_row_to_passage(row) for row in rows)

    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult:
        if not request.query.strip():
            return SemanticCandidateResult(SemanticCandidateStatus.INVALID_QUERY)
        if request.limit < 1 or request.limit > SEMANTIC_MAX_RESULTS:
            return SemanticCandidateResult(
                SemanticCandidateStatus.TOO_MANY_RESULTS,
                max_results=SEMANTIC_MAX_RESULTS,
            )
        if self.state().status is not HistoryProjectionStatus.ENABLED:
            return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)
        try:
            vectors = self._embedder.embed(
                [self._settings.query_prefix + request.query]
            )
            _validate_vectors(vectors, 1, self._settings.dimension)
            rows = self._read_candidate_rows(request)
            query_vector = vectors[0]
            candidates = sorted(
                (
                    SemanticCandidate(
                        passage_id=str(row[0]),
                        reference=JournalEventRef(str(row[1]), int(row[2])),
                        score=_cosine(query_vector, _decode_vector(str(row[7]))),
                    )
                    for row in rows
                ),
                key=lambda candidate: (-candidate.score, candidate.passage_id),
            )
        except SemanticProjectionSchemaError:
            raise
        except Exception as exc:
            self._mark_unavailable(exc, "semantic candidate query failed")
            return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)
        return SemanticCandidateResult(
            SemanticCandidateStatus.ACCEPTED,
            tuple(candidates[: request.limit]),
        )

    def _read_candidate_rows(
        self, request: SemanticCandidateQuery
    ) -> list[tuple[object, ...]]:
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                """
                SELECT passage_id, session_id, event_position, timestamp, role,
                       source, text, vector_json
                FROM semantic_passages
                ORDER BY passage_id
                """
            ).fetchall()
        return [row for row in rows if _matches_filters(row, request)]

    def _replace_index(
        self,
        passages: Sequence[SemanticPassage],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection:
            connection.execute("BEGIN")
            _drop_schema(connection)
            _create_schema(connection)
            _insert_metadata(connection, self.configured_backend)
            for passage, vector in zip(passages, vectors, strict=True):
                self._insert_passage(connection, passage, vector)
            connection.commit()

    def _insert_passage(
        self,
        connection: sqlite3.Connection,
        passage: SemanticPassage,
        vector: Sequence[float],
    ) -> None:
        connection.execute(
            """
            INSERT INTO semantic_passages (
                passage_id, session_id, event_position, timestamp, role, source,
                text, vector_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                passage.passage_id,
                passage.reference.session_id,
                passage.reference.event_position,
                passage.timestamp,
                passage.role,
                passage.source,
                passage.text,
                json.dumps(list(vector), ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def _delete_event(
        self, connection: sqlite3.Connection, reference: JournalEventRef
    ) -> None:
        connection.execute(
            """
            DELETE FROM semantic_passages
            WHERE session_id = ? AND event_position = ?
            """,
            (reference.session_id, reference.event_position),
        )

    def _passage_count(self) -> int:
        if not self._db_path.exists():
            return 0
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM semantic_passages"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _read_backend_identity(
        self,
    ) -> SemanticProjectionBackendIdentity | None:
        if not self._db_path.exists():
            return None
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                "SELECT key, value FROM semantic_projection_meta"
            ).fetchall()
        metadata = {str(key): str(value) for key, value in rows}
        required = {
            _SCHEMA_VERSION_KEY,
            _MODEL_KEY,
            _DIMENSION_KEY,
            _QUERY_PREFIX_KEY,
            _PASSAGE_PREFIX_KEY,
        }
        if not required <= metadata.keys():
            raise SemanticProjectionSchemaError(
                "semantic projection metadata is incomplete"
            )
        return SemanticProjectionBackendIdentity(
            model=metadata[_MODEL_KEY],
            dimension=_parse_dimension(metadata[_DIMENSION_KEY]),
            query_prefix=metadata[_QUERY_PREFIX_KEY],
            passage_prefix=metadata[_PASSAGE_PREFIX_KEY],
        )

    def _check_existing_schema(self) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection:
            names = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }
            required = {"semantic_projection_meta", "semantic_passages"}
            if not required <= names:
                raise SemanticProjectionSchemaError(
                    "semantic projection database has an incomplete schema"
                )
            row = connection.execute(
                """
                SELECT value FROM semantic_projection_meta WHERE key = ?
                """,
                (_SCHEMA_VERSION_KEY,),
            ).fetchone()
        if row is None:
            raise SemanticProjectionSchemaError(
                "semantic projection database has no schema version"
            )
        version = _parse_dimension(str(row[0]))
        if version != CURRENT_SEMANTIC_PROJECTION_SCHEMA_VERSION:
            raise SemanticProjectionSchemaError(
                "unsupported semantic projection schema version: "
                f"{version}; expected {CURRENT_SEMANTIC_PROJECTION_SCHEMA_VERSION}"
            )

    def _mark_unavailable(self, error: Exception, operation: str) -> None:
        self._runtime_error = f"{operation}: {type(error).__name__}: {error}"
        self._logger.exception(operation)


def _passage_from_record(record: JournalEventRecord) -> SemanticPassage | None:
    event = record.event
    if event.role not in {"user", "assistant"} or not event.text.strip():
        return None
    return SemanticPassage(
        passage_id=_passage_id(record.reference),
        reference=record.reference,
        timestamp=event.timestamp,
        role=event.role,
        source=event.source,
        text=event.text,
    )


def _passage_from_corpus_event(event: HistoryCorpusEvent) -> SemanticPassage | None:
    if event.role not in {"user", "assistant"} or not event.text.strip():
        return None
    return SemanticPassage(
        passage_id=_passage_id(event.reference),
        reference=event.reference,
        timestamp=event.timestamp,
        role=event.role,
        source=event.source,
        text=event.text,
    )


def _passage_id(reference: JournalEventRef) -> str:
    return f"{reference.session_id}:{reference.event_position}"


def _validate_vectors(
    vectors: Sequence[Sequence[float]], expected_count: int, dimension: int
) -> None:
    if len(vectors) != expected_count:
        raise ValueError(
            f"embedding provider returned {len(vectors)} vectors; "
            f"expected {expected_count}"
        )
    for vector in vectors:
        if len(vector) != dimension:
            raise ValueError(
                f"embedding dimension {len(vector)} does not match configured "
                f"dimension {dimension}"
            )
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("embedding vector must contain finite numbers")


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _decode_vector(value: str) -> tuple[float, ...]:
    raw = json.loads(value)
    if not isinstance(raw, list):
        raise SemanticProjectionSchemaError("stored semantic vector is not a list")
    if any(not isinstance(item, int | float) or isinstance(item, bool) for item in raw):
        raise SemanticProjectionSchemaError(
            "stored semantic vector contains a non-numeric value"
        )
    return tuple(float(item) for item in raw)


def _row_to_passage(row: Sequence[object]) -> SemanticPassage:
    return SemanticPassage(
        passage_id=str(row[0]),
        reference=JournalEventRef(str(row[1]), int(row[2])),
        timestamp=str(row[3]),
        role=str(row[4]),
        source=str(row[5]),
        text=str(row[6]),
    )


def _matches_filters(row: Sequence[object], request: SemanticCandidateQuery) -> bool:
    if request.session_ids and str(row[1]) not in request.session_ids:
        return False
    timestamp = str(row[3])
    event_date = timestamp[:10]
    if request.date_from is not None and event_date < request.date_from:
        return False
    if request.date_to is not None and event_date > request.date_to:
        return False
    if request.roles and str(row[4]) not in request.roles:
        return False
    return not (request.sources and str(row[5]) not in request.sources)


def _drop_schema(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS semantic_passages")
    connection.execute("DROP TABLE IF EXISTS semantic_projection_meta")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE semantic_projection_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE semantic_passages (
            passage_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            event_position INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            role TEXT NOT NULL,
            source TEXT NOT NULL,
            text TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            UNIQUE (session_id, event_position)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX semantic_passages_session_idx
        ON semantic_passages (session_id, event_position)
        """
    )


def _insert_metadata(
    connection: sqlite3.Connection, identity: SemanticProjectionBackendIdentity
) -> None:
    connection.executemany(
        "INSERT INTO semantic_projection_meta (key, value) VALUES (?, ?)",
        (
            (_SCHEMA_VERSION_KEY, str(CURRENT_SEMANTIC_PROJECTION_SCHEMA_VERSION)),
            (_MODEL_KEY, identity.model),
            (_DIMENSION_KEY, str(identity.dimension)),
            (_QUERY_PREFIX_KEY, identity.query_prefix),
            (_PASSAGE_PREFIX_KEY, identity.passage_prefix),
        ),
    )


def _parse_dimension(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SemanticProjectionSchemaError(
            f"semantic projection metadata dimension is invalid: {value!r}"
        ) from exc
    if parsed <= 0:
        raise SemanticProjectionSchemaError(
            f"semantic projection metadata dimension is invalid: {value!r}"
        )
    return parsed
