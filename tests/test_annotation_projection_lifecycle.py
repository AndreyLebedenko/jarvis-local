from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from jarvis.core.bus import EventBus
from jarvis.journal import (
    Annotation,
    AnnotationOverlayChanged,
    AnnotationOverlayRepository,
    AnnotationSearchIndex,
    AnnotationSearchRequest,
    AnnotationSource,
    AnnotationTarget,
    HistoryProjectionLifecycle,
    UnavailableSemanticHistoryProjection,
)
from jarvis.journal.events import JournalEventRef

_SESSION = "20260801-120000-ab12"


class _AllKnownReferences:
    def event_exists(self, reference: JournalEventRef) -> bool:
        del reference
        return True


class _RecordingAnnotationProjection:
    name = "recording-annotation"

    def __init__(self) -> None:
        self.startup_rebuilds = 0
        self.reprojected: list[str] = []
        self.deleted_annotations: list[str] = []
        self.deleted_sessions: list[str] = []
        self._gate: threading.Event | None = None

    def block_next_reprojection(self) -> threading.Event:
        self._gate = threading.Event()
        return self._gate

    def startup_rebuild(self) -> None:
        self.startup_rebuilds += 1

    def reproject_annotation(self, annotation: Annotation) -> None:
        gate = self._gate
        if gate is not None:
            self._gate = None
            gate.wait(5)
        self.reprojected.append(annotation.annotation_id)

    def delete_annotation_projection(self, annotation_id: str) -> None:
        self.deleted_annotations.append(annotation_id)

    def delete_session_projection(self, session_id: str) -> None:
        self.deleted_sessions.append(session_id)


def _repo(tmp_path: Path) -> AnnotationOverlayRepository:
    return AnnotationOverlayRepository(tmp_path / "derived", _AllKnownReferences())


def _add(repo: AnnotationOverlayRepository, text: str) -> str:
    result = repo.add_annotation(
        AnnotationTarget(_SESSION), text, "author", AnnotationSource.GENERATED
    )
    assert result.annotation_id is not None
    return result.annotation_id


def _lifecycle(
    bus: EventBus,
    repo: AnnotationOverlayRepository,
    projection: _RecordingAnnotationProjection,
) -> HistoryProjectionLifecycle:
    return HistoryProjectionLifecycle(
        bus,
        projections=(),
        semantic_projection=UnavailableSemanticHistoryProjection(),
        annotation_projections=(projection,),
        annotation_source=repo,
    )


@pytest.mark.asyncio
async def test_startup_rebuilds_annotation_projections(tmp_path: Path) -> None:
    bus = EventBus()
    repo = _repo(tmp_path)
    projection = _RecordingAnnotationProjection()
    lifecycle = _lifecycle(bus, repo, projection)

    await lifecycle.start()
    try:
        assert projection.startup_rebuilds == 1
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_change_reprojects_that_annotation(tmp_path: Path) -> None:
    bus = EventBus()
    repo = _repo(tmp_path)
    projection = _RecordingAnnotationProjection()
    lifecycle = _lifecycle(bus, repo, projection)
    annotation_id = _add(repo, "keyword")

    await lifecycle.start()
    try:
        await bus.publish(
            AnnotationOverlayChanged,
            AnnotationOverlayChanged(_SESSION, annotation_id),
        )
        await lifecycle.wait_for_idle()

        assert projection.reprojected == [annotation_id]
        assert projection.deleted_annotations == []
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_change_for_deleted_annotation_drops_projection(tmp_path: Path) -> None:
    bus = EventBus()
    repo = _repo(tmp_path)
    projection = _RecordingAnnotationProjection()
    lifecycle = _lifecycle(bus, repo, projection)
    annotation_id = _add(repo, "keyword")
    repo.delete_annotation(annotation_id)

    await lifecycle.start()
    try:
        await bus.publish(
            AnnotationOverlayChanged,
            AnnotationOverlayChanged(_SESSION, annotation_id),
        )
        await lifecycle.wait_for_idle()

        assert projection.reprojected == []
        assert projection.deleted_annotations == [annotation_id]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_concurrent_changes_coalesce_into_one_rerun(tmp_path: Path) -> None:
    bus = EventBus()
    repo = _repo(tmp_path)
    projection = _RecordingAnnotationProjection()
    lifecycle = _lifecycle(bus, repo, projection)
    annotation_id = _add(repo, "keyword")

    await lifecycle.start()
    try:
        gate = projection.block_next_reprojection()
        first = await _publish(bus, annotation_id)
        # Two more changes arrive while the first re-projection is blocked; they
        # coalesce into exactly one additional rerun, not two.
        second = await _publish(bus, annotation_id)
        third = await _publish(bus, annotation_id)
        gate.set()
        await asyncio.gather(first, second, third)
        await lifecycle.wait_for_idle()

        assert projection.reprojected == [annotation_id, annotation_id]
    finally:
        await lifecycle.close()


@pytest.mark.asyncio
async def test_delete_session_fans_out_to_annotation_projections(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    repo = _repo(tmp_path)
    projection = _RecordingAnnotationProjection()
    lifecycle = _lifecycle(bus, repo, projection)

    await lifecycle.start()
    try:
        lifecycle.delete_session_projections(_SESSION)
        assert projection.deleted_sessions == [_SESSION]
    finally:
        await lifecycle.close()


class _BlockingSearchProjection:
    """Wraps a real search index but blocks inside one re-projection.

    Lets a test hold an annotation re-projection open (inside the lifecycle's
    write lock) while it attempts a concurrent session deletion.
    """

    name = "blocking-annotation-search"

    def __init__(self, index: AnnotationSearchIndex) -> None:
        self._index = index
        self.entered = threading.Event()
        self.release = threading.Event()

    def startup_rebuild(self) -> None:
        self._index.startup_rebuild()

    def reproject_annotation(self, annotation: Annotation) -> None:
        self.entered.set()
        self.release.wait(5)
        self._index.reproject_annotation(annotation)

    def delete_annotation_projection(self, annotation_id: str) -> None:
        self._index.delete_annotation_projection(annotation_id)

    def delete_session_projection(self, session_id: str) -> None:
        self._index.delete_session_projection(session_id)


@pytest.mark.asyncio
async def test_deleted_session_does_not_reappear_via_inflight_reprojection(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    repo = _repo(tmp_path)
    index = AnnotationSearchIndex(repo, tmp_path / "derived")
    index.rebuild()
    projection = _BlockingSearchProjection(index)
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(),
        semantic_projection=UnavailableSemanticHistoryProjection(),
        annotation_projections=(projection,),
        annotation_source=repo,
    )
    annotation_id = _add(repo, "keyword must stay deleted")

    await lifecycle.start()
    try:
        await _publish(bus, annotation_id)
        # The re-projection is now inside the write lock, mid-write.
        assert await asyncio.to_thread(projection.entered.wait, 5)

        deletion = asyncio.ensure_future(
            asyncio.to_thread(lifecycle.delete_session_projections, _SESSION)
        )
        await asyncio.sleep(0.05)
        # Deletion must block on the write lock until the re-projection finishes.
        assert not deletion.done()

        projection.release.set()
        await deletion
        await lifecycle.wait_for_idle()

        result = index.search(AnnotationSearchRequest(query="keyword"))
        assert result.hits == ()
    finally:
        projection.release.set()
        await lifecycle.close()


async def _publish(bus: EventBus, annotation_id: str) -> asyncio.Task[None]:
    return asyncio.ensure_future(
        bus.publish(
            AnnotationOverlayChanged,
            AnnotationOverlayChanged(_SESSION, annotation_id),
        )
    )
