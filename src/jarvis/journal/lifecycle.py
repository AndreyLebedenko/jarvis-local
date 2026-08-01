from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from jarvis.core.bus import EventBus
from jarvis.journal.corpus import HistoryCorpusRepository
from jarvis.journal.events import JournalEventAppended, JournalEventRecord
from jarvis.journal.search import JournalSearchHit, JournalSearchIndex
from jarvis.journal.store import (
    JournalReplay,
    JournalSessionSummary,
    JournalStore,
    JournalUsage,
)


class HistoryProjectionStatus(Enum):
    ENABLED = "enabled"
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
    ) -> None:
        self._bus = bus
        self._projections = projections
        self._semantic_projection = semantic_projection
        self._logger = logger or logging.getLogger(__name__)
        self._create_task = create_task or asyncio.create_task
        self._pending_tasks: set[asyncio.Task[None]] = set()
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
            self._subscribed = True

    async def close(self) -> None:
        async with self._start_lock:
            if self._subscribed:
                self._bus.unsubscribe(
                    JournalEventAppended, self._on_journal_event_appended
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
