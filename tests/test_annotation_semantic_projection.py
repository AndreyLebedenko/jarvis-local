from __future__ import annotations

from pathlib import Path

import httpx

from jarvis.core.config import HistorySemanticSettings
from jarvis.journal.annotation import (
    AnnotationOverlayRepository,
    AnnotationSource,
    AnnotationStatus,
    AnnotationTarget,
)
from jarvis.journal.annotation_semantic import (
    AnnotationSemanticIndex,
    AnnotationSemanticQuery,
    AnnotationSemanticStatus,
)
from jarvis.journal.events import JournalEventRef
from jarvis.journal.lifecycle import HistoryProjectionStatus

_SESSION = "20260801-120000-ab12"
_OTHER_SESSION = "20260802-090000-cd34"


class _AllKnownReferences:
    def event_exists(self, reference: JournalEventRef) -> bool:
        del reference
        return True


def _repo(tmp_path: Path) -> AnnotationOverlayRepository:
    return AnnotationOverlayRepository(tmp_path / "derived", _AllKnownReferences())


def _add(
    repo: AnnotationOverlayRepository,
    text: str,
    *,
    session_id: str = _SESSION,
    source: AnnotationSource = AnnotationSource.GENERATED,
    status: AnnotationStatus = AnnotationStatus.ACTIVE,
) -> str:
    result = repo.add_annotation(
        AnnotationTarget(session_id), text, "author", source, status
    )
    assert result.accepted, result.status
    assert result.annotation_id is not None
    return result.annotation_id


def _settings(
    *, model: str = "test-model", enabled: bool = True
) -> HistorySemanticSettings:
    return HistorySemanticSettings(
        enabled=enabled,
        model=model,
        query_prefix="query: ",
        passage_prefix="passage: ",
        dimension=2,
    )


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        return [(1.0, 0.0) if "alpha" in text else (0.0, 1.0) for text in texts]


class _TimeoutEmbedder:
    def embed(self, texts: tuple[str, ...] | list[str]) -> list[tuple[float, ...]]:
        del texts
        raise httpx.TimeoutException("query embedding timed out")


def _index(
    tmp_path: Path,
    repo: AnnotationOverlayRepository,
    embedder: _FakeEmbedder | None = None,
    settings: HistorySemanticSettings | None = None,
    query_embedder: object | None = None,
) -> AnnotationSemanticIndex:
    return AnnotationSemanticIndex(
        repo,
        tmp_path / "derived",
        settings or _settings(),
        embedder or _FakeEmbedder(),
        query_embedder=query_embedder,
    )


def test_rebuild_embeds_only_active_annotations(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add(repo, "alpha passage")
    _add(repo, "dismissed", status=AnnotationStatus.DISMISSED)
    index = _index(tmp_path, repo)

    index.rebuild()

    assert index.state().status is HistoryProjectionStatus.ENABLED
    assert [passage.text for passage in index.list_passages()] == ["alpha passage"]


def test_query_returns_scored_annotation_ids(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    alpha_id = _add(repo, "alpha passage")
    beta_id = _add(repo, "beta passage")
    index = _index(tmp_path, repo)
    index.rebuild()

    result = index.query(AnnotationSemanticQuery("alpha wins", limit=2))

    assert result.status is AnnotationSemanticStatus.ACCEPTED
    assert result.candidates[0].annotation_id == alpha_id
    assert result.candidates[0].score == 1.0
    assert {candidate.annotation_id for candidate in result.candidates} == {
        alpha_id,
        beta_id,
    }


def test_reproject_updates_one_annotation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "beta passage")
    embedder = _FakeEmbedder()
    index = _index(tmp_path, repo, embedder)
    index.rebuild()
    repo.update_annotation(annotation_id, text="alpha passage")

    updated = repo.read_annotation(annotation_id).annotation
    assert updated is not None
    index.reproject_annotation(updated)

    assert [passage.text for passage in index.list_passages()] == ["alpha passage"]
    assert embedder.calls[-1] == ("passage: alpha passage",)


def test_reproject_removes_dismissed_annotation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "alpha passage")
    index = _index(tmp_path, repo)
    index.rebuild()
    repo.update_annotation(annotation_id, status=AnnotationStatus.DISMISSED)

    dismissed = repo.read_annotation(annotation_id).annotation
    assert dismissed is not None
    index.reproject_annotation(dismissed)

    assert index.list_passages() == ()


def test_delete_annotation_projection_removes_row(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "alpha passage")
    index = _index(tmp_path, repo)
    index.rebuild()

    index.delete_annotation_projection(annotation_id)

    assert index.list_passages() == ()


def test_delete_session_removes_only_that_session(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add(repo, "alpha here", session_id=_SESSION)
    _add(repo, "beta there", session_id=_OTHER_SESSION)
    index = _index(tmp_path, repo)
    index.rebuild()

    index.delete_session_projection(_SESSION)

    assert [passage.session_id for passage in index.list_passages()] == [_OTHER_SESSION]


def test_query_session_filter(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    here = _add(repo, "alpha here", session_id=_SESSION)
    _add(repo, "alpha there", session_id=_OTHER_SESSION)
    index = _index(tmp_path, repo)
    index.rebuild()

    result = index.query(AnnotationSemanticQuery("alpha", session_ids=(_SESSION,)))

    assert [candidate.annotation_id for candidate in result.candidates] == [here]


def test_query_source_filter(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    generated = _add(repo, "alpha generated", source=AnnotationSource.GENERATED)
    _add(repo, "alpha edited", source=AnnotationSource.EDITED)
    index = _index(tmp_path, repo)
    index.rebuild()

    result = index.query(AnnotationSemanticQuery("alpha", sources=("generated",)))

    assert [candidate.annotation_id for candidate in result.candidates] == [generated]


def test_disabled_projection_is_unavailable_and_writes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add(repo, "alpha passage")
    index = _index(tmp_path, repo, settings=_settings(enabled=False))

    index.rebuild()
    result = index.query(AnnotationSemanticQuery("alpha"))

    assert index.state().status is HistoryProjectionStatus.UNAVAILABLE
    assert result.status is AnnotationSemanticStatus.UNAVAILABLE
    assert not index.db_path.exists()


def test_backend_mismatch_is_unavailable_until_rebuilt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add(repo, "alpha passage")
    first = _index(tmp_path, repo, settings=_settings(model="model-a"))
    first.rebuild()

    second = _index(tmp_path, repo, settings=_settings(model="model-b"))

    assert second.state().status is HistoryProjectionStatus.UNAVAILABLE
    second.rebuild_if_backend_changed()
    assert second.state().status is HistoryProjectionStatus.ENABLED


def test_query_reports_timeout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add(repo, "alpha passage")
    index = _index(tmp_path, repo, query_embedder=_TimeoutEmbedder())
    index.rebuild()

    result = index.query(AnnotationSemanticQuery("alpha"))

    assert result.status is AnnotationSemanticStatus.TIMEOUT
