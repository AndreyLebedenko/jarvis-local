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
    EffectiveTranscriptResolver,
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
_COMPLETE_KEY = "complete"


class SemanticProjectionSchemaError(Exception):
    """Raised when a semantic index cannot be safely interpreted."""


class SemanticEmbeddingFailed(Exception):
    """Raised when embedding fails for every passage during a rebuild.

    Carries only a passage count and the backend error's type name, never a
    passage's text or a backend error message. Either of those could contain
    content, and the projection must not leak content through the failure it
    reports.
    """


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...


class OllamaEmbeddingProvider:
    """Small synchronous seam for Ollama's local embedding endpoint."""

    def __init__(
        self,
        settings: BackendSettings,
        semantic_settings: HistorySemanticSettings,
        client: httpx.Client | None = None,
        *,
        connect_timeout_seconds: float | None = None,
        read_timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings
        self._semantic_settings = semantic_settings
        self._client = client
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        if self._client is not None:
            return self._embed_with_client(self._client, texts)
        read_timeout_seconds = (
            self._read_timeout_seconds
            if self._read_timeout_seconds is not None
            else self._settings.read_timeout_seconds
        )
        connect_timeout_seconds = (
            self._connect_timeout_seconds
            if self._connect_timeout_seconds is not None
            else 10.0
        )
        # Keep connect fail-fast separate from the read budget:
        # rebuild can wait longer for a response, but it should still
        # notice a dead Ollama quickly.
        timeout = httpx.Timeout(
            read_timeout_seconds,
            connect=connect_timeout_seconds,
            write=read_timeout_seconds,
            pool=read_timeout_seconds,
        )
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


class CachingQueryEmbeddingProvider:
    """Memoizes the most recent embedding request.

    Both the event and annotation semantic indices embed the same per-turn
    query string (identical prefix and model), one after the other, when the
    retrieval service fuses their candidates. Sharing one instance of this
    wrapper as their ``query_embedder`` collapses those two calls into a single
    model forward pass: the second lookup hits the cache. The cache holds only
    the last request as one atomically-assigned ``(key, value)`` tuple, so a
    concurrent turn with a different query can at worst force a recompute, never
    return a vector for the wrong text.
    """

    def __init__(self, inner: EmbeddingProvider) -> None:
        self._inner = inner
        self._cache: tuple[tuple[str, ...], list[tuple[float, ...]]] | None = None

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        key = tuple(texts)
        cache = self._cache
        if cache is not None and cache[0] == key:
            return cache[1]
        value = self._inner.embed(texts)
        self._cache = (key, value)
        return value


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
    TIMEOUT = "timeout"
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
        *,
        query_embedder: EmbeddingProvider | None = None,
        transcripts: EffectiveTranscriptResolver | None = None,
    ) -> None:
        self._repository = repository
        self._db_path = root / SEMANTIC_PROJECTION_DB_NAME
        self._settings = settings
        self._embedder = embedder
        self._query_embedder = query_embedder or embedder
        self._logger = logger or logging.getLogger(__name__)
        self._transcripts = transcripts
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
        # An incomplete stored index skipped a passage that failed to embed;
        # rebuild so it gets another chance now that a transient cause (a backend
        # hiccup, a model reloaded with a larger context) may have cleared.
        if stored == self.configured_backend and not self._stored_index_is_incomplete():
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
            texts = [self._settings.passage_prefix + p.text for p in passages]
            labels = [p.passage_id for p in passages]
            kept, vectors = embed_texts_resiliently(
                self._embedder, texts, labels, self._settings.dimension, self._logger
            )
            self._replace_index(
                [passages[index] for index in kept],
                vectors,
                complete=len(kept) == len(passages),
            )
        except SemanticProjectionSchemaError:
            raise
        except Exception as exc:
            self._mark_unavailable(exc, "semantic projection rebuild failed")
            return
        self._runtime_error = None

    def project_event(self, record: JournalEventRecord) -> None:
        if self.state().status is not HistoryProjectionStatus.ENABLED:
            return
        passage = self._passage_from_record(record)
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
            self._mark_stored_index_incomplete()

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
            vectors = self._query_embedder.embed(
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
        except httpx.TimeoutException:
            return SemanticCandidateResult(SemanticCandidateStatus.TIMEOUT)
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
        *,
        complete: bool,
    ) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection:
            connection.execute("BEGIN")
            _drop_schema(connection)
            _create_schema(connection)
            _insert_metadata(connection, self.configured_backend, complete=complete)
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

    def _stored_index_is_incomplete(self) -> bool:
        # A pre-flag index (no "complete" row) is treated as complete: it was
        # written before per-passage skipping existed, so it skipped nothing.
        if not self._db_path.exists():
            return False
        self._check_existing_schema()
        with closing(sqlite3.connect(self._db_path)) as connection:
            row = connection.execute(
                "SELECT value FROM semantic_projection_meta WHERE key = ?",
                (_COMPLETE_KEY,),
            ).fetchone()
        return row is not None and str(row[0]) == "0"

    def _mark_stored_index_incomplete(self) -> None:
        # A live update that failed to embed left this event's passage missing
        # or stale. Flip the persisted flag so the next startup rebuilds instead
        # of trusting a complete-looking index. Best-effort: we are already on a
        # failure path, so a meta-write problem is logged, not raised.
        if not self._db_path.exists():
            return
        try:
            self._check_existing_schema()
            with closing(sqlite3.connect(self._db_path)) as connection, connection:
                connection.execute(
                    "INSERT OR REPLACE INTO semantic_projection_meta (key, value) "
                    "VALUES (?, '0')",
                    (_COMPLETE_KEY,),
                )
        except Exception:
            self._logger.exception("failed to mark semantic index incomplete")

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

    def _passage_from_record(
        self, record: JournalEventRecord
    ) -> SemanticPassage | None:
        event = record.event
        if event.role not in {"user", "assistant"}:
            return None
        text = self._effective_text(record.reference, event.text)
        if not text.strip():
            return None
        return SemanticPassage(
            passage_id=_passage_id(record.reference),
            reference=record.reference,
            timestamp=event.timestamp,
            role=event.role,
            source=event.source,
            text=text,
        )

    def _effective_text(self, reference: JournalEventRef, raw_text: str) -> str:
        """Transcript-aware text for the incremental (record) projection path.

        Mirrors the corpus rule so a re-projected voice turn embeds its
        transcript overlay, while a normal turn never consults the overlay.
        """

        if raw_text.strip() or self._transcripts is None:
            return raw_text
        overlay = self._transcripts.transcript_text(reference)
        return overlay if overlay else raw_text


def _passage_from_corpus_event(event: HistoryCorpusEvent) -> SemanticPassage | None:
    if event.role not in {"user", "assistant"} or not event.indexed_text.strip():
        return None
    return SemanticPassage(
        passage_id=_passage_id(event.reference),
        reference=event.reference,
        timestamp=event.timestamp,
        role=event.role,
        source=event.source,
        text=event.indexed_text,
    )


def _passage_id(reference: JournalEventRef) -> str:
    return f"{reference.session_id}:{reference.event_position}"


def embed_texts_resiliently(
    embedder: EmbeddingProvider,
    texts: Sequence[str],
    labels: Sequence[str],
    dimension: int,
    logger: logging.Logger,
) -> tuple[tuple[int, ...], list[tuple[float, ...]]]:
    """Embed texts batch-first, isolating per-text failures on the slow path.

    Returns the indices of texts that embedded successfully and their vectors,
    in order. A single text the backend rejects (an oversized passage is the
    motivating case) is logged and skipped so it cannot void the whole
    projection. If none survive, raises a content-free ``SemanticEmbeddingFailed``
    so the caller can degrade the projection to unavailable.
    """

    try:
        vectors = embedder.embed(list(texts))
        _validate_vectors(vectors, len(texts), dimension)
    except SemanticProjectionSchemaError:
        raise
    except Exception as batch_error:
        return _embed_texts_individually(
            embedder, texts, labels, dimension, logger, batch_error
        )
    return tuple(range(len(texts))), list(vectors)


def _embed_texts_individually(
    embedder: EmbeddingProvider,
    texts: Sequence[str],
    labels: Sequence[str],
    dimension: int,
    logger: logging.Logger,
    batch_error: Exception,
) -> tuple[tuple[int, ...], list[tuple[float, ...]]]:
    kept: list[int] = []
    vectors: list[tuple[float, ...]] = []
    for index, (text, label) in enumerate(zip(texts, labels, strict=True)):
        try:
            embedded = embedder.embed([text])
            _validate_vectors(embedded, 1, dimension)
        except SemanticProjectionSchemaError:
            raise
        except Exception as exc:
            # Type and length only: a backend error message can echo the
            # passage text, which must not leak.
            logger.warning(
                "semantic projection skipped passage %s "
                "(text_length=%d) after embedding failure: %s",
                label,
                len(text),
                type(exc).__name__,
            )
            continue
        kept.append(index)
        vectors.append(embedded[0])
    if not kept:
        # from None: this runs inside the backend error's handler, so implicit
        # chaining would leak its (possibly content-bearing) message into the
        # traceback the caller logs.
        raise SemanticEmbeddingFailed(
            f"all {len(texts)} passages failed to embed ({type(batch_error).__name__})"
        ) from None
    logger.warning(
        "semantic projection rebuilt with %d of %d passages; "
        "%d skipped after per-passage embedding failures",
        len(kept),
        len(texts),
        len(texts) - len(kept),
    )
    return tuple(kept), vectors


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
    connection: sqlite3.Connection,
    identity: SemanticProjectionBackendIdentity,
    *,
    complete: bool,
) -> None:
    connection.executemany(
        "INSERT INTO semantic_projection_meta (key, value) VALUES (?, ?)",
        (
            (_SCHEMA_VERSION_KEY, str(CURRENT_SEMANTIC_PROJECTION_SCHEMA_VERSION)),
            (_MODEL_KEY, identity.model),
            (_DIMENSION_KEY, str(identity.dimension)),
            (_QUERY_PREFIX_KEY, identity.query_prefix),
            (_PASSAGE_PREFIX_KEY, identity.passage_prefix),
            (_COMPLETE_KEY, "1" if complete else "0"),
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
