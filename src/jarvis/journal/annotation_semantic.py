"""Semantic retrieval projection over session annotations (task v1.8.0-23).

A rebuildable, source-grounded semantic index over annotation text, keyed by
``annotation_id`` and physically separate from the event semantic passage index
so an annotation vector can never replace a raw event passage. It reuses the
same embedding backend and configuration (`HistorySemanticSettings`) as the
event index - one query embedding is computed per turn and reused across both
indices by the retrieval service, so adding annotations costs one extra ANN
lookup, not a second model forward pass.

Only ``ACTIVE`` annotations are indexed; a ``DISMISSED`` annotation is removed
from retrieval without being deleted (story-v1.8.0 decision 5). Candidate
results expose ``annotation_id`` and score only; callers hydrate the full
annotation from the overlay store.
"""

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

import httpx

from jarvis.core.config import HistorySemanticSettings
from jarvis.journal.annotation import Annotation, AnnotationStatus
from jarvis.journal.annotation_search import AnnotationListSource
from jarvis.journal.events import parse_journal_timestamp
from jarvis.journal.lifecycle import (
    HistoryProjectionStatus,
    SemanticProjectionBackendIdentity,
    SemanticProjectionState,
)
from jarvis.journal.semantic import (
    EmbeddingProvider,
    SemanticProjectionSchemaError,
)

CURRENT_ANNOTATION_SEMANTIC_SCHEMA_VERSION = 1
ANNOTATION_SEMANTIC_DB_NAME = "annotation_semantic_index.db"
ANNOTATION_SEMANTIC_MAX_RESULTS = 500

_SCHEMA_VERSION_KEY = "schema_version"
_MODEL_KEY = "model"
_DIMENSION_KEY = "dimension"
_QUERY_PREFIX_KEY = "query_prefix"
_PASSAGE_PREFIX_KEY = "passage_prefix"


class AnnotationSemanticStatus(Enum):
    ACCEPTED = "accepted"
    INVALID_QUERY = "invalid_query"
    TOO_MANY_RESULTS = "too_many_results"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AnnotationSemanticPassage:
    annotation_id: str
    session_id: str
    timestamp: str
    source: str
    text: str


@dataclass(frozen=True)
class AnnotationSemanticQuery:
    query: str
    limit: int = ANNOTATION_SEMANTIC_MAX_RESULTS
    session_ids: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnnotationSemanticCandidate:
    annotation_id: str
    session_id: str
    score: float


@dataclass(frozen=True)
class AnnotationSemanticResult:
    status: AnnotationSemanticStatus
    candidates: tuple[AnnotationSemanticCandidate, ...] = ()
    max_results: int = ANNOTATION_SEMANTIC_MAX_RESULTS


class AnnotationSemanticIndex:
    """SQLite-backed semantic annotation projection keyed by ``annotation_id``.

    Implements the ``AnnotationDerivedProjection`` shape: ``startup_rebuild``
    re-embeds only when the configured backend changed, and the per-annotation
    methods keep one row current on an overlay change.
    """

    name = "annotation_semantic"

    def __init__(
        self,
        repository: AnnotationListSource,
        root: Path,
        settings: HistorySemanticSettings,
        embedder: EmbeddingProvider,
        logger: logging.Logger | None = None,
        *,
        query_embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._repository = repository
        self._db_path = root / ANNOTATION_SEMANTIC_DB_NAME
        self._settings = settings
        self._embedder = embedder
        self._query_embedder = query_embedder or embedder
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

    def startup_rebuild(self) -> None:
        self.rebuild_if_backend_changed()

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
                for annotation in self._repository.list_all_annotations()
                if (passage := _passage_from_annotation(annotation)) is not None
            )
            vectors = self._embedder.embed(
                [self._settings.passage_prefix + passage.text for passage in passages]
            )
            _validate_vectors(vectors, len(passages), self._settings.dimension)
            self._replace_index(passages, vectors)
        except SemanticProjectionSchemaError:
            raise
        except Exception as exc:
            self._mark_unavailable(exc, "annotation semantic rebuild failed")
            return
        self._runtime_error = None

    def reproject_annotation(self, annotation: Annotation) -> None:
        if self.state().status is not HistoryProjectionStatus.ENABLED:
            return
        passage = _passage_from_annotation(annotation)
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._db_path)) as connection:
                connection.execute("BEGIN")
                _delete_annotation(connection, annotation.annotation_id)
                if passage is not None:
                    vectors = self._embedder.embed(
                        [self._settings.passage_prefix + passage.text]
                    )
                    _validate_vectors(vectors, 1, self._settings.dimension)
                    _insert_passage(connection, passage, vectors[0])
                connection.commit()
        except SemanticProjectionSchemaError:
            raise
        except Exception as exc:
            self._mark_unavailable(exc, "annotation semantic update failed")

    def delete_annotation_projection(self, annotation_id: str) -> None:
        if not self._db_path.exists():
            return
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            _delete_annotation(connection, annotation_id)

    def delete_session_projection(self, session_id: str) -> None:
        if not self._db_path.exists():
            return
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            connection.execute(
                "DELETE FROM annotation_semantic_passages WHERE session_id = ?",
                (session_id,),
            )

    def list_passages(self) -> tuple[AnnotationSemanticPassage, ...]:
        if not self._db_path.exists():
            return ()
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                """
                SELECT annotation_id, session_id, timestamp, source, text
                FROM annotation_semantic_passages
                ORDER BY annotation_id
                """
            ).fetchall()
        return tuple(
            AnnotationSemanticPassage(
                annotation_id=str(row[0]),
                session_id=str(row[1]),
                timestamp=str(row[2]),
                source=str(row[3]),
                text=str(row[4]),
            )
            for row in rows
        )

    def query(self, request: AnnotationSemanticQuery) -> AnnotationSemanticResult:
        if not request.query.strip():
            return AnnotationSemanticResult(AnnotationSemanticStatus.INVALID_QUERY)
        if request.limit < 1 or request.limit > ANNOTATION_SEMANTIC_MAX_RESULTS:
            return AnnotationSemanticResult(
                AnnotationSemanticStatus.TOO_MANY_RESULTS,
                max_results=ANNOTATION_SEMANTIC_MAX_RESULTS,
            )
        if self.state().status is not HistoryProjectionStatus.ENABLED:
            return AnnotationSemanticResult(AnnotationSemanticStatus.UNAVAILABLE)
        try:
            vectors = self._query_embedder.embed(
                [self._settings.query_prefix + request.query]
            )
            _validate_vectors(vectors, 1, self._settings.dimension)
            rows = self._read_candidate_rows(request)
            query_vector = vectors[0]
            candidates = sorted(
                (
                    AnnotationSemanticCandidate(
                        annotation_id=str(row[0]),
                        session_id=str(row[1]),
                        score=_cosine(query_vector, _decode_vector(str(row[5]))),
                    )
                    for row in rows
                ),
                key=lambda candidate: (-candidate.score, candidate.annotation_id),
            )
        except SemanticProjectionSchemaError:
            raise
        except httpx.TimeoutException:
            return AnnotationSemanticResult(AnnotationSemanticStatus.TIMEOUT)
        except Exception as exc:
            self._mark_unavailable(exc, "annotation semantic query failed")
            return AnnotationSemanticResult(AnnotationSemanticStatus.UNAVAILABLE)
        return AnnotationSemanticResult(
            AnnotationSemanticStatus.ACCEPTED,
            tuple(candidates[: request.limit]),
        )

    def _read_candidate_rows(
        self, request: AnnotationSemanticQuery
    ) -> list[tuple[object, ...]]:
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                """
                SELECT annotation_id, session_id, timestamp, source, text,
                       vector_json
                FROM annotation_semantic_passages
                ORDER BY annotation_id
                """
            ).fetchall()
        return [row for row in rows if _matches_filters(row, request)]

    def _replace_index(
        self,
        passages: Sequence[AnnotationSemanticPassage],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection:
            connection.execute("BEGIN")
            _drop_schema(connection)
            _create_schema(connection)
            _insert_metadata(connection, self.configured_backend)
            for passage, vector in zip(passages, vectors, strict=True):
                _insert_passage(connection, passage, vector)
            connection.commit()

    def _passage_count(self) -> int:
        if not self._db_path.exists():
            return 0
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM annotation_semantic_passages"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _read_backend_identity(self) -> SemanticProjectionBackendIdentity | None:
        if not self._db_path.exists():
            return None
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                "SELECT key, value FROM annotation_semantic_meta"
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
                "annotation semantic metadata is incomplete"
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
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            required = {"annotation_semantic_meta", "annotation_semantic_passages"}
            if not required <= names:
                raise SemanticProjectionSchemaError(
                    "annotation semantic database has an incomplete schema"
                )
            row = connection.execute(
                "SELECT value FROM annotation_semantic_meta WHERE key = ?",
                (_SCHEMA_VERSION_KEY,),
            ).fetchone()
        if row is None:
            raise SemanticProjectionSchemaError(
                "annotation semantic database has no schema version"
            )
        version = _parse_dimension(str(row[0]))
        if version != CURRENT_ANNOTATION_SEMANTIC_SCHEMA_VERSION:
            raise SemanticProjectionSchemaError(
                "unsupported annotation semantic schema version: "
                f"{version}; expected {CURRENT_ANNOTATION_SEMANTIC_SCHEMA_VERSION}"
            )

    def _mark_unavailable(self, error: Exception, operation: str) -> None:
        self._runtime_error = f"{operation}: {type(error).__name__}: {error}"
        self._logger.exception(operation)


def _passage_from_annotation(
    annotation: Annotation,
) -> AnnotationSemanticPassage | None:
    if annotation.status is not AnnotationStatus.ACTIVE or not annotation.text.strip():
        return None
    return AnnotationSemanticPassage(
        annotation_id=annotation.annotation_id,
        session_id=annotation.target.session_id,
        timestamp=annotation.created_at,
        source=annotation.source.value,
        text=annotation.text,
    )


def _insert_passage(
    connection: sqlite3.Connection,
    passage: AnnotationSemanticPassage,
    vector: Sequence[float],
) -> None:
    timestamp = parse_journal_timestamp(passage.timestamp)
    connection.execute(
        """
        INSERT INTO annotation_semantic_passages (
            annotation_id, session_id, timestamp, event_date, source, text,
            vector_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            passage.annotation_id,
            passage.session_id,
            passage.timestamp,
            timestamp.date().isoformat(),
            passage.source,
            passage.text,
            json.dumps(list(vector), ensure_ascii=False, separators=(",", ":")),
        ),
    )


def _delete_annotation(connection: sqlite3.Connection, annotation_id: str) -> None:
    connection.execute(
        "DELETE FROM annotation_semantic_passages WHERE annotation_id = ?",
        (annotation_id,),
    )


def _matches_filters(row: Sequence[object], request: AnnotationSemanticQuery) -> bool:
    if request.session_ids and str(row[1]) not in request.session_ids:
        return False
    event_date = str(row[2])[:10]
    if request.date_from is not None and event_date < request.date_from:
        return False
    if request.date_to is not None and event_date > request.date_to:
        return False
    return not (request.sources and str(row[3]) not in request.sources)


def _drop_schema(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS annotation_semantic_passages")
    connection.execute("DROP TABLE IF EXISTS annotation_semantic_meta")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE annotation_semantic_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE annotation_semantic_passages (
            annotation_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_date TEXT NOT NULL,
            source TEXT NOT NULL,
            text TEXT NOT NULL,
            vector_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX annotation_semantic_session_idx
        ON annotation_semantic_passages (session_id)
        """
    )


def _insert_metadata(
    connection: sqlite3.Connection, identity: SemanticProjectionBackendIdentity
) -> None:
    connection.executemany(
        "INSERT INTO annotation_semantic_meta (key, value) VALUES (?, ?)",
        (
            (_SCHEMA_VERSION_KEY, str(CURRENT_ANNOTATION_SEMANTIC_SCHEMA_VERSION)),
            (_MODEL_KEY, identity.model),
            (_DIMENSION_KEY, str(identity.dimension)),
            (_QUERY_PREFIX_KEY, identity.query_prefix),
            (_PASSAGE_PREFIX_KEY, identity.passage_prefix),
        ),
    )


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


def _parse_dimension(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SemanticProjectionSchemaError(
            f"annotation semantic metadata dimension is invalid: {value!r}"
        ) from exc
    if parsed <= 0:
        raise SemanticProjectionSchemaError(
            f"annotation semantic metadata dimension is invalid: {value!r}"
        )
    return parsed
