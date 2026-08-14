from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from jarvis.core.bus import EventBus
from jarvis.journal.annotation import (
    Annotation,
    AnnotationOverlayChanged,
    AnnotationOverlayRepository,
    AnnotationRead,
)
from jarvis.journal.archive import ArchiveOverlayRepository
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


class AnnotationReprojectionSource(Protocol):
    """Reads one annotation by id for a re-projection.

    ``AnnotationOverlayRepository`` satisfies this structurally. A missing read
    (the annotation was deleted) drives the derived projections to drop the row
    rather than re-index it.
    """

    def read_annotation(self, annotation_id: str) -> AnnotationRead: ...


class AnnotationDerivedProjection(Protocol):
    """A derived retrieval projection over the annotation overlay store.

    Unlike an event ``HistoryProjection``, an annotation projection never
    updates on a raw ``JournalEventAppended`` (annotations are written
    explicitly). It rebuilds at startup, maintains one annotation on an overlay
    change, and clears a session on deletion.
    """

    name: str

    def startup_rebuild(self) -> None: ...

    def reproject_annotation(self, annotation: Annotation) -> None: ...

    def delete_annotation_projection(self, annotation_id: str) -> None: ...

    def delete_session_projection(self, session_id: str) -> None: ...


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


class ArchiveHistoryProjection:
    """Fan-out target for session deletion over the archive metadata store
    (task v1.8.0-25). Like annotations, a run is written only by the explicit
    executor, never derived from an appended raw event, so `project_event` is
    a no-op; only session deletion touches this store.
    """

    name = "archive"

    def __init__(self, repository: ArchiveOverlayRepository) -> None:
        self._repository = repository

    def rebuild(self) -> None:
        self._repository.rebuild()

    def project_event(self, record: JournalEventRecord) -> None:
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
        annotation_projections: tuple[AnnotationDerivedProjection, ...] = (),
        annotation_source: AnnotationReprojectionSource | None = None,
    ) -> None:
        self._bus = bus
        self._projections = projections
        self._semantic_projection = semantic_projection
        self._logger = logger or logging.getLogger(__name__)
        self._create_task = create_task or asyncio.create_task
        self._transcript_event_source = transcript_event_source
        self._annotation_projections = annotation_projections
        self._annotation_source = annotation_source
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._reprojection_active: set[JournalEventRef] = set()
        self._reprojection_pending: set[JournalEventRef] = set()
        self._annotation_active: set[str] = set()
        self._annotation_pending: set[str] = set()
        # Serializes one re-projection's read-then-write (transcript or
        # annotation) against a concurrent session-projection deletion. Without
        # it, a re-projection that read its source before the session was
        # deleted could write the stale row back after deletion cleared the
        # derived projections, so retrieval would resurface a deleted session.
        # A threading lock (not an asyncio one) because it is held across the
        # off-thread projection work and acquired by the on-loop deletion path.
        self._projection_write_lock = threading.Lock()
        self._start_lock = asyncio.Lock()
        self._subscribed = False

    @property
    def _annotations_enabled(self) -> bool:
        return self._annotation_source is not None and bool(
            self._annotation_projections
        )

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
            if self._annotations_enabled:
                self._bus.subscribe(
                    AnnotationOverlayChanged, self._on_annotation_overlay_changed
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
                if self._annotations_enabled:
                    self._bus.unsubscribe(
                        AnnotationOverlayChanged, self._on_annotation_overlay_changed
                    )
                self._subscribed = False
        await self.wait_for_idle()

    async def wait_for_idle(self) -> None:
        while self._pending_tasks:
            pending = tuple(self._pending_tasks)
            await asyncio.gather(*pending)

    def delete_session_projections(self, session_id: str) -> None:
        # The lock makes deletion mutually exclusive with an in-flight
        # re-projection (see _reproject_transcript_event_locked and
        # _reproject_annotation_locked): either the re-projection commits first
        # and this deletion then clears its row, or this deletion commits first
        # and the re-projection observes its source is gone and writes nothing.
        # Both orders end with no derived row for the session.
        with self._projection_write_lock:
            for projection in self._projections:
                projection.delete_session_projection(session_id)
            self._semantic_projection.delete_session_projection(session_id)
            for annotation_projection in self._annotation_projections:
                annotation_projection.delete_session_projection(session_id)

    def _rebuild_startup_projections(self) -> None:
        for projection in self._projections:
            projection.rebuild()
        self._semantic_projection.rebuild_if_backend_changed()
        for annotation_projection in self._annotation_projections:
            annotation_projection.startup_rebuild()

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
            await asyncio.to_thread(self._reproject_transcript_event_locked, reference)
        except Exception:
            self._logger.exception(
                "Transcript re-projection failed for %s:%s",
                reference.session_id,
                reference.event_position,
            )

    def _reproject_transcript_event_locked(self, reference: JournalEventRef) -> None:
        source = self._transcript_event_source
        if source is None:
            return
        # Read the source event and write the derived rows as one critical
        # section, so a concurrent session deletion cannot slip between the read
        # and the write and let a stale row survive (see delete_session_
        # projections). Re-reading under the lock is also what makes deletion win
        # when it commits first: the source event is then already gone.
        with self._projection_write_lock:
            event = source.read_event(reference)
            if event is None:
                # The overlay outlived its source event (e.g. a deleted
                # session). Deletion already removed the derived rows; there is
                # nothing to re-project.
                return
            record = JournalEventRecord(reference, event)
            self._project_event(record)

    async def _on_annotation_overlay_changed(
        self, event: AnnotationOverlayChanged
    ) -> None:
        annotation_id = event.annotation_id
        if annotation_id in self._annotation_active:
            # Serialize re-projection per annotation for the same reason the
            # transcript path does: two concurrent runs could commit the lexical
            # and semantic writes out of order and leave the two projections
            # reflecting different annotation versions. Coalesce into one rerun.
            self._annotation_pending.add(annotation_id)
            return
        self._annotation_active.add(annotation_id)
        task = self._create_task(self._run_annotation_reprojection(annotation_id))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _run_annotation_reprojection(self, annotation_id: str) -> None:
        try:
            while True:
                await self._reproject_annotation(annotation_id)
                # No await between this check and looping/returning, so a change
                # delivered during the run above is observed atomically and
                # coalesced into exactly one rerun.
                if annotation_id not in self._annotation_pending:
                    return
                self._annotation_pending.discard(annotation_id)
        finally:
            self._annotation_active.discard(annotation_id)

    async def _reproject_annotation(self, annotation_id: str) -> None:
        source = self._annotation_source
        if source is None:
            return
        try:
            await asyncio.to_thread(self._reproject_annotation_locked, annotation_id)
        except Exception:
            self._logger.exception(
                "Annotation re-projection failed for %s", annotation_id
            )

    def _reproject_annotation_locked(self, annotation_id: str) -> None:
        source = self._annotation_source
        if source is None:
            return
        # Read the current annotation and write the derived rows as one critical
        # section, so a concurrent session deletion cannot slip between the read
        # and the write and let a stale row survive (see delete_session_
        # projections). Re-reading under the lock is also what makes deletion win
        # when it commits first: the annotation is then already gone.
        with self._projection_write_lock:
            read = source.read_annotation(annotation_id)
            annotation = read.annotation if read.found else None
            if annotation is None:
                # The annotation was deleted (or dismissal removed its row). Drop
                # any derived rows so retrieval cannot resurface it.
                for projection in self._annotation_projections:
                    projection.delete_annotation_projection(annotation_id)
            else:
                for projection in self._annotation_projections:
                    projection.reproject_annotation(annotation)

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
