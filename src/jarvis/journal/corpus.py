from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol

from jarvis.journal.events import (
    JournalEvent,
    JournalEventRecord,
    JournalEventRef,
    JSONValue,
    parse_journal_timestamp,
)
from jarvis.journal.provenance import (
    ProvenanceDescriptor,
    spoken_derivative_provenance_descriptor,
)
from jarvis.journal.store import JournalStore

# Schema version 2 adds the derived ``effective_text`` column: the text a
# retrieval projection should index and hydrate for one event, which is the
# raw event text for a normal turn and the transcript overlay text for a voice
# turn whose raw text is empty. Raw ``text`` stays byte-untouched for
# provenance; ``effective_text`` is a rebuildable derived value.
CURRENT_HISTORY_CORPUS_SCHEMA_VERSION = 2
HISTORY_READ_MAX_EVENTS_PER_RANGE = 200
HISTORY_READ_MAX_BATCH_RANGES = 8
HISTORY_READ_MAX_TOTAL_EVENTS = 500
HISTORY_SEARCH_MAX_RESULTS = 500
_CORPUS_FILE_NAME = "history_corpus.db"
_SCHEMA_VERSION_KEY = "schema_version"
# The mode-3 spoken derivative lives in the journal event's metadata; the
# locator FTS (story-v1.9.1 task 3) projects it, the canonical FTS never sees it.
SPOKEN_DERIVATIVE_METADATA_KEY = "spoken_derivative"
_QUERY_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class HistoryCorpusSchemaError(Exception):
    pass


class EffectiveTranscriptResolver(Protocol):
    """Supplies the derived transcript overlay text for one source event.

    Returns the overlay's effective text (generated or user-edited) for the
    reference, or ``None`` when no overlay exists. The corpus consults it only
    when an event's raw text is empty, so a normal text turn never pays a
    lookup and voice turns become retrievable through their transcript.
    """

    def transcript_text(self, reference: JournalEventRef) -> str | None: ...


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
    effective_text: str = ""

    @property
    def indexed_text(self) -> str:
        """The text retrieval indexes and hydrates for this event.

        Equal to the raw text for a normal turn; the transcript overlay text
        for a voice turn whose raw text is empty. Falls back to raw text when
        no derived value was stored (e.g. a value constructed in a test).
        """

        return self.effective_text or self.text

    @property
    def text_is_transcript(self) -> bool:
        """Whether ``indexed_text`` came from a transcript overlay.

        True only when the raw event carried no text of its own and a
        transcript supplied the indexed text, so a caller can source-frame the
        text as a transcript rather than the user's own words.
        """

        return bool(self.effective_text) and not self.text.strip()


@dataclass(frozen=True)
class HistoryEventRange:
    start: JournalEventRef
    end: JournalEventRef

    @property
    def requested_count(self) -> int:
        if self.start.session_id != self.end.session_id:
            return 0
        if self.end.event_position < self.start.event_position:
            return 0
        return self.end.event_position - self.start.event_position + 1


@dataclass(frozen=True)
class HistorySessionMetadata:
    session_id: str
    first_timestamp: str
    last_timestamp: str
    first_event_position: int
    last_event_position: int
    event_count: int


class HistoryEventReadStatus(Enum):
    FOUND = "found"
    UNKNOWN_REFERENCE = "unknown_reference"


@dataclass(frozen=True)
class HistoryEventRead:
    status: HistoryEventReadStatus
    event: HistoryCorpusEvent | None = None

    @property
    def found(self) -> bool:
        return self.status is HistoryEventReadStatus.FOUND


class HistoryEventRefsReadStatus(Enum):
    ACCEPTED = "accepted"
    TOO_MANY_REFERENCES = "too_many_references"


@dataclass(frozen=True)
class HistoryEventRefsRead:
    status: HistoryEventRefsReadStatus
    events: tuple[HistoryCorpusEvent, ...] = ()
    missing_references: tuple[JournalEventRef, ...] = ()
    max_references: int = HISTORY_READ_MAX_TOTAL_EVENTS


class HistoryEventRangeStatus(Enum):
    FOUND = "found"
    UNKNOWN_REFERENCE = "unknown_reference"
    UNKNOWN_START_REFERENCE = "unknown_start_reference"
    UNKNOWN_END_REFERENCE = "unknown_end_reference"
    CROSS_SESSION = "cross_session"
    REVERSED_RANGE = "reversed_range"
    NEGATIVE_CONTEXT_LIMIT = "negative_context_limit"
    TOO_MANY_EVENTS = "too_many_events"


@dataclass(frozen=True)
class HistoryEventRangeRead:
    status: HistoryEventRangeStatus
    requested_range: HistoryEventRange | None = None
    events: tuple[HistoryCorpusEvent, ...] = ()
    missing_reference: JournalEventRef | None = None
    requested_count: int = 0
    max_events: int = HISTORY_READ_MAX_EVENTS_PER_RANGE


class HistorySessionReadStatus(Enum):
    FOUND = "found"
    UNKNOWN_SESSION = "unknown_session"


@dataclass(frozen=True)
class HistorySessionRead:
    status: HistorySessionReadStatus
    session: HistorySessionMetadata | None = None


class HistoryBatchReadStatus(Enum):
    ACCEPTED = "accepted"
    TOO_MANY_RANGES = "too_many_ranges"
    TOO_MANY_EVENTS = "too_many_events"


@dataclass(frozen=True)
class HistoryBatchRead:
    status: HistoryBatchReadStatus
    ranges: tuple[HistoryEventRangeRead, ...] = ()
    total_events: int = 0
    requested_events: int = 0
    max_ranges: int = HISTORY_READ_MAX_BATCH_RANGES
    max_events: int = HISTORY_READ_MAX_TOTAL_EVENTS


class HistorySearchOrder(Enum):
    RELEVANCE = "relevance"
    CHRONOLOGICAL = "chronological"


class HistorySearchStatus(Enum):
    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"
    INVALID_LIMIT = "invalid_limit"
    TOO_MANY_RESULTS = "too_many_results"
    INVALID_ROLE = "invalid_role"


@dataclass(frozen=True)
class HistorySearchRequest:
    query: str = ""
    term_groups: tuple[tuple[str, ...], ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    session_ids: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    limit: int = 50
    order: HistorySearchOrder = HistorySearchOrder.RELEVANCE


@dataclass(frozen=True)
class HistorySearchHit:
    reference: JournalEventRef
    timestamp: str
    role: str
    source: str
    snippet: str
    score: float
    order_index: int


@dataclass(frozen=True)
class HistoryLocatorHit:
    """One heard-phrase locator match (story-v1.9.1 task 4).

    ``canonical_text`` is the owning event's on-screen text - the only
    authoritative content. ``snippet`` comes from the spoken derivative and
    is for human recognition of what was heard, never authoritative.
    ``provenance`` is the task-1 locator-only descriptor; it makes the
    result impossible to consume as a canonical turn.
    """

    reference: JournalEventRef
    timestamp: str
    snippet: str
    canonical_text: str
    score: float
    order_index: int
    provenance: ProvenanceDescriptor


@dataclass(frozen=True)
class HistoryLocatorRequest:
    query: str = ""
    date_from: str | None = None
    date_to: str | None = None
    session_ids: tuple[str, ...] = ()
    limit: int = 50


@dataclass(frozen=True)
class HistoryLocatorResult:
    status: HistorySearchStatus
    hits: tuple[HistoryLocatorHit, ...] = ()
    max_results: int = HISTORY_SEARCH_MAX_RESULTS


@dataclass(frozen=True)
class HistorySearchResult:
    status: HistorySearchStatus
    hits: tuple[HistorySearchHit, ...] = ()
    max_results: int = HISTORY_SEARCH_MAX_RESULTS


class HistoryCorpusRepository:
    def __init__(
        self,
        store: JournalStore,
        root: Path,
        transcripts: EffectiveTranscriptResolver | None = None,
    ) -> None:
        self._store = store
        self._db_path = root / _CORPUS_FILE_NAME
        self._transcripts = transcripts

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _effective_text(self, event: JournalEvent, reference: JournalEventRef) -> str:
        """Resolve the text to index/hydrate for one event.

        Raw text wins when present, so an ordinary turn never consults the
        overlay store. A voice turn with empty raw text falls back to its
        transcript overlay (when one exists), which is what makes voice content
        retrievable without rewriting the raw journal.
        """

        if event.text.strip():
            return event.text
        if self._transcripts is None:
            return event.text
        overlay = self._transcripts.transcript_text(reference)
        return overlay if overlay else event.text

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
        connection = self._open_read_connection()
        if connection is None:
            return []
        with closing(connection):
            if not _table_exists(connection, "history_corpus_events"):
                return []
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
                    metadata_json,
                    effective_text
                FROM history_corpus_events
                ORDER BY timestamp_sort, session_id, event_position
                """
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def read_event(self, reference: JournalEventRef) -> HistoryEventRead:
        connection = self._open_read_connection()
        if connection is None:
            return HistoryEventRead(HistoryEventReadStatus.UNKNOWN_REFERENCE)
        with closing(connection):
            row = self._fetch_event(connection, reference)
            if row is None:
                return HistoryEventRead(HistoryEventReadStatus.UNKNOWN_REFERENCE)
            return HistoryEventRead(
                HistoryEventReadStatus.FOUND, self._row_to_event(row)
            )

    def read_events(
        self, references: tuple[JournalEventRef, ...]
    ) -> HistoryEventRefsRead:
        if len(references) > HISTORY_READ_MAX_TOTAL_EVENTS:
            return HistoryEventRefsRead(
                HistoryEventRefsReadStatus.TOO_MANY_REFERENCES,
                max_references=HISTORY_READ_MAX_TOTAL_EVENTS,
            )

        connection = self._open_read_connection()
        if connection is None:
            events_by_ref = {}
        else:
            with closing(connection):
                events_by_ref = self._fetch_events_by_reference(connection, references)
        events: list[HistoryCorpusEvent] = []
        missing: list[JournalEventRef] = []
        for reference in references:
            event = events_by_ref.get(reference)
            if event is None:
                missing.append(reference)
            else:
                events.append(event)
        return HistoryEventRefsRead(
            HistoryEventRefsReadStatus.ACCEPTED,
            tuple(events),
            tuple(missing),
            HISTORY_READ_MAX_TOTAL_EVENTS,
        )

    def read_range(self, event_range: HistoryEventRange) -> HistoryEventRangeRead:
        invalid = self._validate_range_shape(
            event_range, max_events=HISTORY_READ_MAX_EVENTS_PER_RANGE
        )
        if invalid is not None:
            return invalid

        connection = self._open_read_connection()
        if connection is None:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.UNKNOWN_START_REFERENCE,
                requested_range=event_range,
                missing_reference=event_range.start,
                requested_count=event_range.requested_count,
            )
        with closing(connection):
            return self._read_range_with_connection(
                connection,
                event_range,
                max_events=HISTORY_READ_MAX_EVENTS_PER_RANGE,
            )

    def read_surrounding(
        self, reference: JournalEventRef, *, before: int, after: int
    ) -> HistoryEventRangeRead:
        if before < 0 or after < 0:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.NEGATIVE_CONTEXT_LIMIT,
                missing_reference=reference,
            )
        connection = self._open_read_connection()
        if connection is None:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.UNKNOWN_REFERENCE,
                missing_reference=reference,
                requested_count=before + after + 1,
            )
        with closing(connection):
            anchor = self._fetch_event(connection, reference)
            if anchor is None:
                return HistoryEventRangeRead(
                    HistoryEventRangeStatus.UNKNOWN_REFERENCE,
                    missing_reference=reference,
                    requested_count=before + after + 1,
                )
            session = self._fetch_session_metadata(connection, reference.session_id)
            if session is None:
                return HistoryEventRangeRead(
                    HistoryEventRangeStatus.UNKNOWN_REFERENCE,
                    missing_reference=reference,
                    requested_count=before + after + 1,
                )
            start = max(session.first_event_position, reference.event_position - before)
            end = min(session.last_event_position, reference.event_position + after)
            event_range = HistoryEventRange(
                JournalEventRef(reference.session_id, start),
                JournalEventRef(reference.session_id, end),
            )
            requested_count = event_range.requested_count
            if requested_count > HISTORY_READ_MAX_EVENTS_PER_RANGE:
                return HistoryEventRangeRead(
                    HistoryEventRangeStatus.TOO_MANY_EVENTS,
                    requested_range=event_range,
                    missing_reference=reference,
                    requested_count=requested_count,
                    max_events=HISTORY_READ_MAX_EVENTS_PER_RANGE,
                )
            return self._read_range_with_connection(
                connection,
                event_range,
                max_events=HISTORY_READ_MAX_EVENTS_PER_RANGE,
            )

    def read_session(self, session_id: str) -> HistorySessionRead:
        connection = self._open_read_connection()
        if connection is None:
            return HistorySessionRead(HistorySessionReadStatus.UNKNOWN_SESSION)
        with closing(connection):
            metadata = self._fetch_session_metadata(connection, session_id)
        if metadata is None:
            return HistorySessionRead(HistorySessionReadStatus.UNKNOWN_SESSION)
        return HistorySessionRead(HistorySessionReadStatus.FOUND, metadata)

    def read_ranges(self, ranges: tuple[HistoryEventRange, ...]) -> HistoryBatchRead:
        if len(ranges) > HISTORY_READ_MAX_BATCH_RANGES:
            return HistoryBatchRead(
                HistoryBatchReadStatus.TOO_MANY_RANGES,
                max_ranges=HISTORY_READ_MAX_BATCH_RANGES,
            )
        requested_events = sum(event_range.requested_count for event_range in ranges)
        if requested_events > HISTORY_READ_MAX_TOTAL_EVENTS:
            return HistoryBatchRead(
                HistoryBatchReadStatus.TOO_MANY_EVENTS,
                requested_events=requested_events,
                max_events=HISTORY_READ_MAX_TOTAL_EVENTS,
            )
        connection = self._open_read_connection()
        if connection is None:
            range_reads = tuple(
                HistoryEventRangeRead(
                    HistoryEventRangeStatus.UNKNOWN_START_REFERENCE,
                    requested_range=event_range,
                    missing_reference=event_range.start,
                    requested_count=event_range.requested_count,
                )
                for event_range in ranges
            )
        else:
            with closing(connection):
                range_reads = tuple(
                    self._read_range_with_connection(
                        connection,
                        event_range,
                        max_events=HISTORY_READ_MAX_EVENTS_PER_RANGE,
                    )
                    for event_range in ranges
                )
        return HistoryBatchRead(
            HistoryBatchReadStatus.ACCEPTED,
            ranges=range_reads,
            total_events=sum(len(range_read.events) for range_read in range_reads),
            requested_events=requested_events,
            max_ranges=HISTORY_READ_MAX_BATCH_RANGES,
            max_events=HISTORY_READ_MAX_TOTAL_EVENTS,
        )

    def search(self, request: HistorySearchRequest) -> HistorySearchResult:
        invalid = _validate_search_request(request)
        if invalid is not None:
            return invalid
        connection = self._open_read_connection()
        if connection is None:
            return HistorySearchResult(HistorySearchStatus.UNAVAILABLE)
        with closing(connection):
            if not _table_exists(connection, "history_corpus_event_fts"):
                return HistorySearchResult(HistorySearchStatus.UNAVAILABLE)
            rows = connection.execute(
                _search_sql(request),
                _search_parameters(request),
            ).fetchall()
        hits = tuple(
            HistorySearchHit(
                reference=JournalEventRef(str(row[0]), int(row[1])),
                timestamp=str(row[2]),
                role=str(row[3]),
                source=str(row[4]),
                snippet=str(row[5]),
                score=float(row[6]),
                order_index=index,
            )
            for index, row in enumerate(rows)
        )
        return HistorySearchResult(HistorySearchStatus.ACCEPTED, hits)

    def search_locator(self, request: HistoryLocatorRequest) -> HistoryLocatorResult:
        """Heard-phrase locator search over the task-3 derivative FTS.

        Mirrors the canonical `search` query dialect (prefix tokens, same
        date-bound parsing) but queries only
        `history_corpus_derivative_fts`; a locator phrase can never surface
        through the canonical FTS and vice versa. Each hit hydrates the
        owning event's canonical `text` from the store as the authoritative
        content and tags the result with the task-1 locator-only provenance.
        """
        if request.limit < 1:
            return HistoryLocatorResult(HistorySearchStatus.INVALID_LIMIT)
        if request.limit > HISTORY_SEARCH_MAX_RESULTS:
            return HistoryLocatorResult(
                HistorySearchStatus.TOO_MANY_RESULTS,
                max_results=HISTORY_SEARCH_MAX_RESULTS,
            )
        # A locator search is a phrase lookup: without a heard phrase there
        # is nothing to locate, so a date-only (or empty) request matches
        # nothing rather than listing every derivative ever spoken.
        if not _to_prefix_match_query(request.query):
            return HistoryLocatorResult(HistorySearchStatus.ACCEPTED)
        connection = self._open_read_connection()
        if connection is None:
            return HistoryLocatorResult(HistorySearchStatus.UNAVAILABLE)
        with closing(connection):
            if not _table_exists(connection, "history_corpus_derivative_fts"):
                return HistoryLocatorResult(HistorySearchStatus.UNAVAILABLE)
            rows = connection.execute(
                _locator_search_sql(request),
                _locator_search_parameters(request),
            ).fetchall()
            hits = []
            for index, row in enumerate(rows):
                reference = JournalEventRef(str(row[0]), int(row[1]))
                canonical_text = self._read_canonical_event_text(connection, reference)
                hits.append(
                    HistoryLocatorHit(
                        reference=reference,
                        timestamp=str(row[2]),
                        snippet=str(row[3]),
                        canonical_text=canonical_text,
                        score=float(row[4]),
                        order_index=index,
                        provenance=spoken_derivative_provenance_descriptor(reference),
                    )
                )
        return HistoryLocatorResult(HistorySearchStatus.ACCEPTED, tuple(hits))

    def _read_canonical_event_text(
        self, connection: sqlite3.Connection, reference: JournalEventRef
    ) -> str:
        row = connection.execute(
            """
            SELECT text
            FROM history_corpus_events
            WHERE session_id = ? AND event_position = ?
            """,
            (reference.session_id, reference.event_position),
        ).fetchone()
        return str(row[0]) if row is not None else ""

    def delete_session_projection(self, session_id: str) -> None:
        if not self._db_path.exists():
            return
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            self._delete_session_projection(connection, session_id)

    def project_event(self, record: JournalEventRecord) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            self._delete_event_projection(connection, record.reference)
            self._insert_record(connection, record)

    def update_session_projection(self, session_id: str) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection, connection:
            self._ensure_schema(connection)
            self._delete_session_projection(connection, session_id)
            replay = self._store.read_session(session_id)
            self._insert_records(connection, replay.records)

    def _insert_all_events(self, connection: sqlite3.Connection) -> None:
        for session in self._store.list_sessions():
            replay = self._store.read_session(session.session_id)
            self._insert_records(connection, replay.records)

    def _insert_records(
        self, connection: sqlite3.Connection, records: list[JournalEventRecord]
    ) -> None:
        for record in records:
            self._insert_record(connection, record)

    def _insert_record(
        self, connection: sqlite3.Connection, record: JournalEventRecord
    ) -> None:
        reference = record.reference
        event = record.event
        timestamp = parse_journal_timestamp(event.timestamp)
        effective_text = self._effective_text(event, reference)
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
                metadata_json,
                effective_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference.session_id,
                reference.event_position,
                event.timestamp,
                timestamp.timestamp(),
                event.role,
                event.source,
                event.text,
                _json_dumps(list(event.media)),
                len(event.media),
                event.transcript,
                _json_dumps(event.metadata),
                effective_text,
            ),
        )
        # Insert parity across both FTS tables: the canonical projection guards
        # on user/assistant roles with non-empty effective text; the locator
        # projection (story-v1.9.1 task 3) indexes only the mode-3 spoken
        # derivative of assistant events. The two inserts share the key
        # (session_id, event_position) and both live inside the same record
        # insert, so neither table can gain a row the other path would miss
        # on delete.
        if event.role in {"user", "assistant"} and effective_text.strip():
            connection.execute(
                """
                INSERT INTO history_corpus_event_fts (
                    session_id,
                    event_position,
                    timestamp,
                    timestamp_sort,
                    event_date,
                    role,
                    source,
                    text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference.session_id,
                    reference.event_position,
                    event.timestamp,
                    timestamp.timestamp(),
                    timestamp.date().isoformat(),
                    event.role,
                    event.source,
                    effective_text,
                ),
            )
        derivative = event.metadata.get(SPOKEN_DERIVATIVE_METADATA_KEY)
        if event.role == "assistant" and isinstance(derivative, str):
            derivative_text = derivative.strip()
            if derivative_text:
                connection.execute(
                    """
                    INSERT INTO history_corpus_derivative_fts (
                        session_id,
                        event_position,
                        timestamp,
                        timestamp_sort,
                        text
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        reference.session_id,
                        reference.event_position,
                        event.timestamp,
                        timestamp.timestamp(),
                        derivative_text,
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
                effective_text TEXT NOT NULL DEFAULT '',
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
        self._create_fts_schema(connection)

    def _create_fts_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS history_corpus_event_fts USING fts5(
                session_id UNINDEXED,
                event_position UNINDEXED,
                timestamp UNINDEXED,
                timestamp_sort UNINDEXED,
                event_date UNINDEXED,
                role UNINDEXED,
                source UNINDEXED,
                text,
                tokenize = 'unicode61',
                prefix = '1 2 3 4 5 6 7 8 9 10'
            )
            """
        )
        self._create_derivative_fts_schema(connection)

    def _create_derivative_fts_schema(self, connection: sqlite3.Connection) -> None:
        # Locator-only surface (story-v1.9.1 task 3), physically separate from
        # the canonical FTS: a derivative phrase must never be matchable
        # through `history_corpus_event_fts MATCH`. Same tokenizer/prefix
        # settings so query behavior matches task 4's expectations.
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS history_corpus_derivative_fts
            USING fts5(
                session_id UNINDEXED,
                event_position UNINDEXED,
                timestamp UNINDEXED,
                timestamp_sort UNINDEXED,
                text,
                tokenize = 'unicode61',
                prefix = '1 2 3 4 5 6 7 8 9 10'
            )
            """
        )

    def _drop_existing_schema(self, connection: sqlite3.Connection) -> None:
        views = _schema_objects(connection, "view")
        tables = _schema_objects(connection, "table")
        for name in views:
            connection.execute(f"DROP VIEW IF EXISTS {_quote_sql_identifier(name)}")
        for name in tables:
            connection.execute(f"DROP TABLE IF EXISTS {_quote_sql_identifier(name)}")

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if _table_exists(connection, "history_corpus_meta"):
            self._check_schema_version(connection)
            if not _table_exists(connection, "history_corpus_event_fts"):
                self._create_fts_schema(connection)
            elif not _table_exists(connection, "history_corpus_derivative_fts"):
                # Additive guard (story-v1.9.1 task 3): an existing corpus DB
                # gains the locator table without a schema-version bump.
                self._create_derivative_fts_schema(connection)
            return
        self._create_schema(connection)

    def _delete_session_projection(
        self, connection: sqlite3.Connection, session_id: str
    ) -> None:
        # Delete parity across both FTS tables and the event store: every
        # locator-table delete mirrors the canonical one with the same
        # predicate, so the tables cannot drift through a one-sided edit.
        connection.execute(
            "DELETE FROM history_corpus_event_fts WHERE session_id = ?",
            (session_id,),
        )
        connection.execute(
            "DELETE FROM history_corpus_derivative_fts WHERE session_id = ?",
            (session_id,),
        )
        connection.execute(
            "DELETE FROM history_corpus_events WHERE session_id = ?",
            (session_id,),
        )

    def _delete_event_projection(
        self, connection: sqlite3.Connection, reference: JournalEventRef
    ) -> None:
        parameters = (reference.session_id, reference.event_position)
        connection.execute(
            """
            DELETE FROM history_corpus_event_fts
            WHERE session_id = ? AND event_position = ?
            """,
            parameters,
        )
        connection.execute(
            """
            DELETE FROM history_corpus_derivative_fts
            WHERE session_id = ? AND event_position = ?
            """,
            parameters,
        )
        connection.execute(
            """
            DELETE FROM history_corpus_events
            WHERE session_id = ? AND event_position = ?
            """,
            parameters,
        )

    def _check_existing_schema_version(self) -> None:
        if not self._db_path.exists():
            return
        with closing(_connect_sqlite_read_only(self._db_path)) as connection:
            self._check_schema_version(connection)

    def _check_schema_version(self, connection: sqlite3.Connection) -> None:
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

    def _open_read_connection(self) -> sqlite3.Connection | None:
        if not self._db_path.exists():
            return None
        connection = _connect_sqlite_read_only(self._db_path)
        try:
            self._check_schema_version(connection)
            return connection
        except Exception:
            connection.close()
            raise

    def _fetch_event(
        self, connection: sqlite3.Connection, reference: JournalEventRef
    ) -> sqlite3.Row | tuple[object, ...] | None:
        if not _table_exists(connection, "history_corpus_events"):
            return None
        return connection.execute(
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
                metadata_json,
                effective_text
            FROM history_corpus_events
            WHERE session_id = ? AND event_position = ?
            """,
            (reference.session_id, reference.event_position),
        ).fetchone()

    def _fetch_events_by_reference(
        self, connection: sqlite3.Connection, references: tuple[JournalEventRef, ...]
    ) -> dict[JournalEventRef, HistoryCorpusEvent]:
        if not references:
            return {}
        unique_references = tuple(dict.fromkeys(references))
        if not unique_references or not _table_exists(
            connection, "history_corpus_events"
        ):
            return {}
        values_sql = ", ".join("(?, ?)" for _ in unique_references)
        parameters: list[str | int] = []
        for reference in unique_references:
            parameters.extend((reference.session_id, reference.event_position))
        rows = connection.execute(
            f"""
            WITH requested(session_id, event_position) AS (
                VALUES {values_sql}
            )
            SELECT
                events.session_id,
                events.event_position,
                events.timestamp,
                events.timestamp_sort,
                events.role,
                events.source,
                events.text,
                events.media_json,
                events.media_count,
                events.transcript,
                events.metadata_json,
                events.effective_text
            FROM requested
            JOIN history_corpus_events AS events
              ON events.session_id = requested.session_id
             AND events.event_position = requested.event_position
            """,
            parameters,
        ).fetchall()
        events = tuple(self._row_to_event(row) for row in rows)
        return {event.reference: event for event in events}

    def _read_range_with_connection(
        self,
        connection: sqlite3.Connection,
        event_range: HistoryEventRange,
        *,
        max_events: int,
    ) -> HistoryEventRangeRead:
        invalid = self._validate_range_shape(event_range, max_events=max_events)
        if invalid is not None:
            return invalid
        if not _table_exists(connection, "history_corpus_events"):
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.UNKNOWN_START_REFERENCE,
                requested_range=event_range,
                missing_reference=event_range.start,
                requested_count=event_range.requested_count,
            )
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
                metadata_json,
                effective_text
            FROM history_corpus_events
            WHERE session_id = ?
              AND event_position >= ?
              AND event_position <= ?
            ORDER BY event_position
            """,
            (
                event_range.start.session_id,
                event_range.start.event_position,
                event_range.end.event_position,
            ),
        ).fetchall()
        events = tuple(self._row_to_event(row) for row in rows)
        positions = {event.reference.event_position for event in events}
        if event_range.start.event_position not in positions:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.UNKNOWN_START_REFERENCE,
                requested_range=event_range,
                missing_reference=event_range.start,
                requested_count=event_range.requested_count,
                max_events=max_events,
            )
        if event_range.end.event_position not in positions:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.UNKNOWN_END_REFERENCE,
                requested_range=event_range,
                missing_reference=event_range.end,
                requested_count=event_range.requested_count,
                max_events=max_events,
            )
        return HistoryEventRangeRead(
            HistoryEventRangeStatus.FOUND,
            requested_range=event_range,
            events=events,
            requested_count=event_range.requested_count,
            max_events=max_events,
        )

    def _fetch_session_metadata(
        self, connection: sqlite3.Connection, session_id: str
    ) -> HistorySessionMetadata | None:
        if not _table_exists(connection, "history_corpus_events"):
            return None
        row = connection.execute(
            """
            SELECT
                MIN(timestamp_sort),
                MAX(timestamp_sort),
                MIN(event_position),
                MAX(event_position),
                COUNT(*)
            FROM history_corpus_events
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None or int(row[4]) == 0:
            return None
        first_timestamp = self._fetch_session_boundary_timestamp(
            connection, session_id, "first"
        )
        last_timestamp = self._fetch_session_boundary_timestamp(
            connection, session_id, "last"
        )
        if first_timestamp is None or last_timestamp is None:
            return None
        return HistorySessionMetadata(
            session_id=session_id,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            first_event_position=int(row[2]),
            last_event_position=int(row[3]),
            event_count=int(row[4]),
        )

    def _validate_range_shape(
        self, event_range: HistoryEventRange, *, max_events: int
    ) -> HistoryEventRangeRead | None:
        if event_range.start.session_id != event_range.end.session_id:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.CROSS_SESSION,
                requested_range=event_range,
            )
        if event_range.end.event_position < event_range.start.event_position:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.REVERSED_RANGE,
                requested_range=event_range,
            )
        requested_count = event_range.requested_count
        if requested_count > max_events:
            return HistoryEventRangeRead(
                HistoryEventRangeStatus.TOO_MANY_EVENTS,
                requested_range=event_range,
                requested_count=requested_count,
                max_events=max_events,
            )
        return None

    @staticmethod
    def _fetch_session_boundary_timestamp(
        connection: sqlite3.Connection,
        session_id: str,
        boundary: Literal["first", "last"],
    ) -> str | None:
        direction = "ASC" if boundary == "first" else "DESC"
        row = connection.execute(
            f"""
            SELECT timestamp
            FROM history_corpus_events
            WHERE session_id = ?
            ORDER BY event_position {direction}
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    @staticmethod
    def _row_to_event(row: sqlite3.Row | tuple[object, ...]) -> HistoryCorpusEvent:
        media = _json_load_list(row[7], "media_json")
        metadata = _json_load_object(row[10], "metadata_json")
        text = str(row[6])
        effective_text = str(row[11]) if row[11] is not None else text
        return HistoryCorpusEvent(
            reference=JournalEventRef(str(row[0]), int(row[1])),
            timestamp=str(row[2]),
            timestamp_sort=float(row[3]),
            role=str(row[4]),
            source=str(row[5]),
            text=text,
            media=tuple(media),
            media_count=int(row[8]),
            transcript=None if row[9] is None else str(row[9]),
            metadata=metadata,
            effective_text=effective_text,
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


def _connect_sqlite_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _validate_search_request(
    request: HistorySearchRequest,
) -> HistorySearchResult | None:
    if request.limit < 1:
        return HistorySearchResult(HistorySearchStatus.INVALID_LIMIT)
    if request.limit > HISTORY_SEARCH_MAX_RESULTS:
        return HistorySearchResult(HistorySearchStatus.TOO_MANY_RESULTS)
    valid_roles = {"user", "assistant", "system"}
    if any(role not in valid_roles for role in request.roles):
        return HistorySearchResult(HistorySearchStatus.INVALID_ROLE)
    return None


def _search_sql(request: HistorySearchRequest) -> str:
    where_sql = _search_where_sql(request)
    snippet_source = "1" if _to_match_query(request) else "0"
    score_sql = (
        "bm25(history_corpus_event_fts)"
        if request.order is HistorySearchOrder.RELEVANCE
        else "CAST(timestamp_sort AS REAL)"
    )
    order_sql = _search_order_sql(request.order)
    return f"""
        SELECT
            session_id,
            event_position,
            timestamp,
            role,
            source,
            CASE
                WHEN {snippet_source} THEN
                    snippet(history_corpus_event_fts, 7, '[', ']', '...', 24)
                ELSE text
            END,
            {score_sql}
        FROM history_corpus_event_fts
        {where_sql}
        {order_sql}
        LIMIT ?
    """


def _search_where_sql(request: HistorySearchRequest) -> str:
    where_parts = _search_where_parts(request)
    if not where_parts:
        return ""
    return "WHERE " + " AND ".join(where_parts)


def _search_where_parts(request: HistorySearchRequest) -> list[str]:
    where_parts: list[str] = []
    if _to_match_query(request):
        where_parts.append("history_corpus_event_fts MATCH ?")
    _append_date_filter(where_parts, request.date_from, "date_from")
    _append_date_filter(where_parts, request.date_to, "date_to")
    _append_in_filter(where_parts, "session_id", request.session_ids)
    _append_in_filter(where_parts, "role", request.roles)
    _append_in_filter(where_parts, "source", request.sources)
    return where_parts


def _locator_search_sql(request: HistoryLocatorRequest) -> str:
    where_parts: list[str] = []
    match_query = _to_prefix_match_query(request.query)
    if match_query:
        where_parts.append("history_corpus_derivative_fts MATCH ?")
    # The locator table has no ``event_date`` column (task-3 row shape), so
    # date bounds resolve to ``timestamp_sort`` comparisons always; the
    # timestamp column stores full ISO timestamps, which compare correctly
    # against both ISO dates resolved to midnight boundaries via
    # _parse_date_bound below.
    _append_locator_date_filter(where_parts, request.date_from, "date_from")
    _append_locator_date_filter(where_parts, request.date_to, "date_to")
    _append_in_filter(where_parts, "session_id", request.session_ids)
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    return f"""
        SELECT
            session_id,
            event_position,
            timestamp,
            snippet(history_corpus_derivative_fts, 4, '[', ']', '...', 24),
            bm25(history_corpus_derivative_fts)
        FROM history_corpus_derivative_fts
        {where_sql}
        ORDER BY
            bm25(history_corpus_derivative_fts),
            timestamp_sort,
            session_id,
            event_position
        LIMIT ?
    """


def _append_locator_date_filter(
    where_parts: list[str], value: str | None, field: Literal["date_from", "date_to"]
) -> None:
    if value is None:
        return
    # Validates the bound parses; the matching parameter is appended by
    # _append_locator_date_param in the same order.
    _parse_date_bound(value)
    operator = ">=" if field == "date_from" else "<="
    where_parts.append(f"timestamp_sort {operator} ?")


def _locator_search_parameters(
    request: HistoryLocatorRequest,
) -> list[str | int | float]:
    parameters: list[str | int | float] = []
    match_query = _to_prefix_match_query(request.query)
    if match_query:
        parameters.append(match_query)
    _append_locator_date_param(parameters, request.date_from, "date_from")
    _append_locator_date_param(parameters, request.date_to, "date_to")
    parameters.extend(request.session_ids)
    parameters.append(request.limit)
    return parameters


def _append_locator_date_param(
    parameters: list[str | int | float],
    value: str | None,
    field: Literal["date_from", "date_to"],
) -> None:
    if value is None:
        return
    bound = _parse_date_bound(value)
    if isinstance(bound, datetime):
        parameters.append(bound.timestamp())
    elif field == "date_to":
        parameters.append(
            datetime.combine(bound, datetime.min.time()).timestamp() + 86399.0
        )
    else:
        parameters.append(datetime.combine(bound, datetime.min.time()).timestamp())


def _search_parameters(request: HistorySearchRequest) -> list[str | int | float]:
    parameters: list[str | int | float] = []
    match_query = _to_match_query(request)
    if match_query:
        parameters.append(match_query)
    _append_date_parameters(parameters, request.date_from, "date_from")
    _append_date_parameters(parameters, request.date_to, "date_to")
    parameters.extend(request.session_ids)
    parameters.extend(request.roles)
    parameters.extend(request.sources)
    parameters.append(request.limit)
    return parameters


def _search_order_sql(order: HistorySearchOrder) -> str:
    if order is HistorySearchOrder.RELEVANCE:
        return """
        ORDER BY
            bm25(history_corpus_event_fts),
            timestamp_sort,
            session_id,
            event_position
        """
    return """
        ORDER BY
            timestamp_sort,
            session_id,
            event_position
    """


def _append_in_filter(
    where_parts: list[str], column: str, values: tuple[str, ...]
) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    where_parts.append(f"{column} IN ({placeholders})")


def _append_date_filter(
    where_parts: list[str], value: str | None, field: Literal["date_from", "date_to"]
) -> None:
    if value is None:
        return
    bound = _parse_date_bound(value)
    operator = ">=" if field == "date_from" else "<="
    column = "timestamp_sort" if isinstance(bound, datetime) else "event_date"
    where_parts.append(f"{column} {operator} ?")


def _append_date_parameters(
    parameters: list[str | int | float],
    value: str | None,
    field: Literal["date_from", "date_to"],
) -> None:
    if value is None:
        return
    bound = _parse_date_bound(value)
    if isinstance(bound, datetime):
        parameters.append(bound.timestamp())
    else:
        parameters.append(bound.isoformat())


def _to_prefix_match_query(query: str) -> str:
    tokens = _QUERY_TOKEN_PATTERN.findall(query.casefold())
    return " AND ".join(f"{token}*" for token in tokens)


def _to_match_query(request: HistorySearchRequest) -> str:
    if not request.term_groups:
        return _to_prefix_match_query(request.query)
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


def _parse_date_bound(value: str) -> date | datetime:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return parse_journal_timestamp(value)


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
