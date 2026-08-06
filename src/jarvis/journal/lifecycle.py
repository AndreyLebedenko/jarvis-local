from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from jarvis.core.bus import EventBus
from jarvis.journal.annotation import AnnotationOverlayRepository
from jarvis.journal.corpus import HistoryCorpusRepository
from jarvis.journal.events import (
    JournalEvent,
    JournalEventAppended,
    JournalEventRecord,
    JournalEventRef,
)
from jarvis.journal.search import JournalSearchHit, JournalSearchIndex
from jarvis.journal.store import (
    JournalReplay,
    JournalSessionSummary,
    JournalStore,
    JournalUsage,
)
from jarvis.journal.transcript import (
    TranscriptOverlayChanged,
    TranscriptOverlayRepository,
)


class TranscriptReprojectionSource(Protocol):
    """Reads the raw source event for a transcript re-projection.

    Validation is against the authoritative raw journal, so a transcript
    written for a valid event always re-projects even if a derived projection
    lagged the original append.
    """

    def read_event(self, reference: JournalEventRef) -> JournalEvent | None: ...


class HistoryProjectionStatus(Enum):
    ENABLED = "enabled"
    UNBUILT = "unbuilt"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SemanticProjectionBackendIdentity:
    model: str
    dimension: int
    query_prefix: str
    passage_prefix: str


@dataclass(frozen=True)
class SemanticProjectionState:
    status: HistoryProjectionStatus
    configured_backend: SemanticProjectionBackendIdentity | None = None
    stored_backend: SemanticProjectionBackendIdentity | None = None
    passage_count: int = 0
    last_error: str | None = None


class HistoryProjection(Protocol):
    name: str

    def rebuild(self) -> None: ...

    def project_event(self, record: JournalEventRecord) -> None: ...

    def delete_session_projection(self, session_id: str) -> None: ...


class SemanticHistoryProjection(HistoryProjection, Protocol):
    def state(self) -> SemanticProjectionState: ...

    def rebuild_if_backend_changed(self) -> None: ...


class UnavailableSemanticHistoryProjection:
    name = "semantic"

    def __init__(
        self,
        configured_backend: SemanticProjectionBackendIdentity | None = None,
    ) -> None:
        self._configured_backend = configured_backend

    def state(self) -> SemanticProjectionState:
        return SemanticProjectionState(
            HistoryProjectionStatus.UNAVAILABLE,
            configured_backend=self._configured_backend,
        )

    def rebuild(self) -> None:
        return

    def rebuild_if_backend_changed(self) -> None:
        return

    def project_event(self, record: JournalEventRecord) -> None:
        del record

    def delete_session_projection(self, session_id: str) -> None:
        del session_id


class CorpusHistoryProjection:
    name = "corpus"

    def __init__(self, repository: HistoryCorpusRepository) -> None:
        self._repository = repository

    def rebuild(self) -> None:
        self._repository.rebuild()

    def project_event(self, record: JournalEventRecord) -> None:
        self._repository.project_event(record)

    def delete_session_projection(self, session_id: str) -> None:
        self._repository.delete_session_projection(session_id)


class JournalStoreEventReferenceResolver:
    """Resolves event existence against the authoritative raw journal.

    The raw journal is the source of truth; derived projections such as the
    corpus are rebuildable and may lag a fresh append or a not-yet-rebuilt
    startup, so a transcript overlay's reference is validated here, never
    against a projection whose transient state could reject a valid event.
    """

    def __init__(self, store: JournalStore) -> None:
        self._store = store

    def event_exists(self, reference: JournalEventRef) -> bool:
        records = self._store.read_session(reference.session_id).records
        return (
            reference.event_position < len(records)
            and records[reference.event_position].reference == reference
        )


class TranscriptHistoryProjection:
    name = "transcript"

    def __init__(self, repository: TranscriptOverlayRepository) -> None:
        self._repository = repository

    def rebuild(self) -> None:
        self._repository.rebuild()

    def project_event(self, record: JournalEventRecord) -> None:
        del record

    def delete_session_projection(self, session_id: str) -> None:
        self._repository.delete_session(session_id)


class AnnotationHistoryProjection:
    name = "annotation"

    def __init__(self, repository: AnnotationOverlayRepository) -> None:
        self._repository = repository

    def rebuild(self) -> None:
        self._repository.rebuild()

    def project_event(self, record: JournalEventRecord) -> None:
        # Annotations are written explicitly, never derived from an appended
        # raw event, so an append projects nothing here. Session deletion is
        # the only lifecycle path that touches the overlay store.
        del record

    def delete_session_projection(self, session_id: str) -> None:
        self._repository.delete_session(session_id)


class HistoryProjectionConsistencyError(Exception):
    pass


class JournalHistoryService:
    def __init__(
        self,
        store: JournalStore,
        lifecycle: HistoryProjectionLifecycle,
        search_index: JournalSearchIndex,
    ) -> None:
        self._store = store
        self._lifecycle = lifecycle
        self._search_index = search_index

    @property
    def root(self) -> Path:
        return self._store.root

    def list_sessions(self) -> list[JournalSessionSummary]:
        return self._store.list_sessions()

    def read_session(self, session_id: str) -> JournalReplay:
        return self._store.read_session(session_id)

    def usage(self) -> JournalUsage:
        return self._store.usage()

    def search(
        self,
        query: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[JournalSearchHit]:
        return self._search_index.search(
            query,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    def delete_session(self, session_id: str) -> None:
        self._store.delete_session(session_id)
        try:
            self._lifecycle.delete_session_projections(session_id)
        except Exception as exc:
            raise HistoryProjectionConsistencyError(
                f"Deleted raw journal session {session_id}, but derived "
                "projection deletion failed"
            ) from exc


class HistoryProjectionLifecycle:
    def __init__(
        self,
        bus: EventBus,
        *,
        projections: tuple[HistoryProjection, ...],
        semantic_projection: SemanticHistoryProjection,
        logger: logging.Logger | None = None,
        create_task: Callable[[Coroutine[object, object, None]], asyncio.Task[None]]
        | None = None,
        transcript_event_source: TranscriptReprojectionSource | None = None,
    ) -> None:
        self._bus = bus
        self._projections = projections
        self._semantic_projection = semantic_projection
        self._logger = logger or logging.getLogger(__name__)
        self._create_task = create_task or asyncio.create_task
        self._transcript_event_source = transcript_event_source
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._reprojection_active: set[JournalEventRef] = set()
        self._reprojection_pending: set[JournalEventRef] = set()
        self._start_lock = asyncio.Lock()
        self._subscribed = False

    @property
    def semantic_state(self) -> SemanticProjectionState:
        return self._semantic_projection.state()

    async def start(self) -> None:
        async with self._start_lock:
            if self._subscribed:
                return
            await asyncio.to_thread(self._rebuild_startup_projections)
            self._bus.subscribe(JournalEventAppended, self._on_journal_event_appended)
            if self._transcript_event_source is not None:
                self._bus.subscribe(
                    TranscriptOverlayChanged, self._on_transcript_overlay_changed
                )
            self._subscribed = True

    async def close(self) -> None:
        async with self._start_lock:
            if self._subscribed:
                self._bus.unsubscribe(
                    JournalEventAppended, self._on_journal_event_appended
                )
                if self._transcript_event_source is not None:
                    self._bus.unsubscribe(
                        TranscriptOverlayChanged, self._on_transcript_overlay_changed
                    )
                self._subscribed = False
        await self.wait_for_idle()

    async def wait_for_idle(self) -> None:
        while self._pending_tasks:
            pending = tuple(self._pending_tasks)
            await asyncio.gather(*pending)

    def delete_session_projections(self, session_id: str) -> None:
        for projection in self._projections:
            projection.delete_session_projection(session_id)
        self._semantic_projection.delete_session_projection(session_id)

    def _rebuild_startup_projections(self) -> None:
        for projection in self._projections:
            projection.rebuild()
        self._semantic_projection.rebuild_if_backend_changed()

    async def _on_journal_event_appended(self, event: JournalEventAppended) -> None:
        record = JournalEventRecord(event.reference, event.event)
        task = self._create_task(self._project_appended_event(record))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _on_transcript_overlay_changed(
        self, event: TranscriptOverlayChanged
    ) -> None:
        reference = event.reference
        if reference in self._reprojection_active:
            # A re-projection for this event is already running. Two concurrent
            # runs for one reference could commit the corpus and semantic
            # writes out of order and leave them reflecting different overlay
            # versions. Mark the in-flight run to repeat once instead, so
            # re-projection stays serialized per event and always ends reading
            # the current overlay.
            self._reprojection_pending.add(reference)
            return
        self._reprojection_active.add(reference)
        task = self._create_task(self._run_transcript_reprojection(reference))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _run_transcript_reprojection(self, reference: JournalEventRef) -> None:
        try:
            while True:
                await self._reproject_transcript_event(reference)
                # No await between this check and either looping or returning,
                # so an overlay change delivered during the run above is
                # observed atomically and coalesced into exactly one rerun.
                if reference not in self._reprojection_pending:
                    return
                self._reprojection_pending.discard(reference)
        finally:
            self._reprojection_active.discard(reference)

    async def _reproject_transcript_event(self, reference: JournalEventRef) -> None:
        source = self._transcript_event_source
        if source is None:
            return
        try:
            event = await asyncio.to_thread(source.read_event, reference)
            if event is None:
                # The overlay outlived its source event (e.g. a deleted
                # session). Deletion already removed the derived rows; there is
                # nothing to re-project.
                return
            record = JournalEventRecord(reference, event)
            await asyncio.to_thread(self._project_event, record)
        except Exception:
            self._logger.exception(
                "Transcript re-projection failed for %s:%s",
                reference.session_id,
                reference.event_position,
            )

    async def _project_appended_event(self, record: JournalEventRecord) -> None:
        try:
            await asyncio.to_thread(self._project_event, record)
        except Exception:
            self._logger.exception(
                "History projection update failed for %s:%s",
                record.reference.session_id,
                record.reference.event_position,
            )

    def _project_event(self, record: JournalEventRecord) -> None:
        for projection in self._projections:
            projection.project_event(record)
        self._semantic_projection.project_event(record)
