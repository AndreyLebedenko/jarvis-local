from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from jarvis.core.bus import EventBus
from jarvis.journal import (
    CorpusHistoryProjection,
    HistoryCorpusRepository,
    HistoryProjectionLifecycle,
    HistoryProjectionStatus,
    HistorySearchRequest,
    JournalEvent,
    JournalEventAppended,
    JournalEventRecord,
    JournalEventRef,
    JournalHistoryService,
    JournalSearchIndex,
    JournalSessionSummary,
    JournalStore,
    SemanticProjectionState,
    UnavailableSemanticHistoryProjection,
)


@pytest.mark.asyncio
async def test_lifecycle_rebuilds_projections_without_ui(tmp_path: Path) -> None:
    bus = EventBus()
    store = JournalStore(tmp_path / "journal")
    store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="startup searchable",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(CorpusHistoryProjection(repository),),
        semantic_projection=UnavailableSemanticHistoryProjection(),
    )

    await lifecycle.start()
    try:
        result = repository.search(HistorySearchRequest("startup"))

        assert [hit.snippet for hit in result.hits] == ["[startup] searchable"]
        assert lifecycle.semantic_state.status is HistoryProjectionStatus.UNAVAILABLE
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_lifecycle_start_is_idempotent(tmp_path: Path) -> None:
    bus = EventBus()
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )
    projection = CorpusHistoryProjection(repository)
    semantic = _FakeSemanticProjection()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(projection,),
        semantic_projection=semantic,
    )

    await lifecycle.start()
    await lifecycle.start()
    try:
        assert semantic.rebuild_if_backend_changed_calls == 1
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_lifecycle_concurrent_start_rebuilds_and_subscribes_once() -> None:
    bus = EventBus()
    projection = _BlockingRebuildProjection()
    semantic = _FakeSemanticProjection()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(projection,),
        semantic_projection=semantic,
    )

    first_start = asyncio.create_task(lifecycle.start())
    assert await asyncio.to_thread(projection.rebuild_started.wait, 5)
    second_start = asyncio.create_task(lifecycle.start())
    projection.release_rebuild()
    await asyncio.gather(first_start, second_start)
    try:
        event = _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:31:00+01:00",
            role="assistant",
            source="assistant",
            text="new answer",
        )
        reference = JournalEventRef(event.session_id, 0)

        await bus.publish(
            JournalEventAppended,
            JournalEventAppended(reference=reference, event=event),
        )
        await lifecycle.wait_for_idle()

        assert projection.rebuild_calls == 1
        assert semantic.rebuild_if_backend_changed_calls == 1
        assert projection.projected == [reference]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_lifecycle_asks_semantic_projection_to_rebuild_backend_mismatch(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    repository = HistoryCorpusRepository(
        JournalStore(tmp_path / "journal"), tmp_path / "derived"
    )
    semantic = _FakeSemanticProjection()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(CorpusHistoryProjection(repository),),
        semantic_projection=semantic,
    )

    await lifecycle.start()
    try:
        assert semantic.rebuild_if_backend_changed_calls == 1
        assert semantic.rebuild_calls == 0
        assert lifecycle.semantic_state.status is HistoryProjectionStatus.ENABLED
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_lifecycle_projects_appended_event_without_replaying_session(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path / "journal")
    first_reference = store.append(
        _event(
            session_id="20260716-153000-ab12",
            timestamp="2026-07-16T15:30:00+01:00",
            role="assistant",
            source="assistant",
            text="old answer",
        )
    )
    repository = HistoryCorpusRepository(store, tmp_path / "derived")
    repository.rebuild()
    second_event = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:31:00+01:00",
        role="assistant",
        source="assistant",
        text="new answer",
    )
    second_reference = JournalEventRef(second_event.session_id, 1)
    failing_store_repository = HistoryCorpusRepository(
        _FailingReadStore(tmp_path / "journal"), tmp_path / "derived"
    )
    failing_store_repository.project_event(
        JournalEventRecord(second_reference, second_event)
    )

    result = repository.search(HistorySearchRequest("answer"))
    assert [hit.reference for hit in result.hits] == [
        first_reference,
        second_reference,
    ]


@pytest.mark.asyncio
async def test_lifecycle_subscriber_returns_before_projection_finishes() -> None:
    bus = EventBus()
    projection = _BlockingProjection()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(projection,),
        semantic_projection=UnavailableSemanticHistoryProjection(),
    )
    await lifecycle.start()
    event = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:31:00+01:00",
        role="assistant",
        source="assistant",
        text="new answer",
    )
    reference = JournalEventRef(event.session_id, 0)

    try:
        await bus.publish(
            JournalEventAppended,
            JournalEventAppended(reference=reference, event=event),
        )

        assert projection.projected == []
        projection.release()
        await lifecycle.wait_for_idle()
        assert projection.projected == [reference]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_lifecycle_logs_projection_error_and_wait_for_idle_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(_FailingProjection(),),
        semantic_projection=UnavailableSemanticHistoryProjection(),
    )
    await lifecycle.start()
    event = _event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:31:00+01:00",
        role="assistant",
        source="assistant",
        text="new answer",
    )

    await bus.publish(
        JournalEventAppended,
        JournalEventAppended(
            reference=JournalEventRef(event.session_id, 0), event=event
        ),
    )
    try:
        await lifecycle.wait_for_idle()
    finally:
        await lifecycle.close()

    assert "History projection update failed" in caplog.text


def test_history_service_deletes_raw_and_derived_session(tmp_path: Path) -> None:
    bus = EventBus()
    store = JournalStore(tmp_path / "journal")
    deleted_session = "20260716-153000-ab12"
    kept_session = "20260717-153000-cd34"
    for session_id, text in (
        (deleted_session, "deleted answer"),
        (kept_session, "kept answer"),
    ):
        store.append(
            _event(
                session_id=session_id,
                timestamp="2026-07-16T15:30:00+01:00",
                role="assistant",
                source="assistant",
                text=text,
            )
        )
    search_index = JournalSearchIndex(store, tmp_path / "derived")
    repository = search_index.repository
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(CorpusHistoryProjection(repository),),
        semantic_projection=UnavailableSemanticHistoryProjection(),
    )
    repository.rebuild()
    service = JournalHistoryService(store, lifecycle, search_index)

    service.delete_session(deleted_session)

    assert [hit.snippet for hit in service.search("answer")] == ["kept [answer]"]
    assert [summary.session_id for summary in service.list_sessions()] == [kept_session]


class _FailingReadStore(JournalStore):
    def list_sessions(self) -> list[JournalSessionSummary]:
        return []

    def read_session(self, session_id: str):  # type: ignore[no-untyped-def]
        raise RuntimeError(session_id)


class _BlockingProjection:
    name = "blocking"

    def __init__(self) -> None:
        self._release = threading.Event()
        self.projected: list[JournalEventRef] = []

    def rebuild(self) -> None:
        return

    def project_event(self, record: JournalEventRecord) -> None:
        self._release.wait(timeout=5)
        self.projected.append(record.reference)

    def delete_session_projection(self, session_id: str) -> None:
        del session_id

    def release(self) -> None:
        self._release.set()


class _BlockingRebuildProjection:
    name = "blocking_rebuild"

    def __init__(self) -> None:
        self.rebuild_started = threading.Event()
        self._release_rebuild = threading.Event()
        self.rebuild_calls = 0
        self.projected: list[JournalEventRef] = []

    def rebuild(self) -> None:
        self.rebuild_calls += 1
        self.rebuild_started.set()
        self._release_rebuild.wait(timeout=5)

    def project_event(self, record: JournalEventRecord) -> None:
        self.projected.append(record.reference)

    def delete_session_projection(self, session_id: str) -> None:
        del session_id

    def release_rebuild(self) -> None:
        self._release_rebuild.set()


class _FailingProjection:
    name = "failing"

    def rebuild(self) -> None:
        return

    def project_event(self, record: JournalEventRecord) -> None:
        raise RuntimeError(record.reference.session_id)

    def delete_session_projection(self, session_id: str) -> None:
        del session_id


class _FakeSemanticProjection:
    name = "semantic"

    def __init__(self) -> None:
        self.rebuild_calls = 0
        self.rebuild_if_backend_changed_calls = 0

    def state(self) -> SemanticProjectionState:
        return SemanticProjectionState(HistoryProjectionStatus.ENABLED)

    def rebuild(self) -> None:
        self.rebuild_calls += 1

    def rebuild_if_backend_changed(self) -> None:
        self.rebuild_if_backend_changed_calls += 1

    def project_event(self, record: JournalEventRecord) -> None:
        del record

    def delete_session_projection(self, session_id: str) -> None:
        del session_id


def _event(
    *,
    session_id: str,
    timestamp: str,
    role: str,
    source: str,
    text: str,
) -> JournalEvent:
    return JournalEvent(
        session_id=session_id,
        timestamp=timestamp,
        source=source,
        role=role,
        text=text,
        media=(),
        transcript=None,
    )
