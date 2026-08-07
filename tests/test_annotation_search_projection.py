from __future__ import annotations

from pathlib import Path

from jarvis.journal.annotation import (
    AnnotationOverlayRepository,
    AnnotationSource,
    AnnotationStatus,
    AnnotationTarget,
)
from jarvis.journal.annotation_search import (
    AnnotationSearchIndex,
    AnnotationSearchRequest,
    AnnotationSearchStatus,
)
from jarvis.journal.events import JournalEventRef

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
        AnnotationTarget(session_id),
        text,
        "annotation-generator",
        source,
        status,
    )
    assert result.accepted, result.status
    assert result.annotation_id is not None
    return result.annotation_id


def _index(tmp_path: Path, repo: AnnotationOverlayRepository) -> AnnotationSearchIndex:
    index = AnnotationSearchIndex(repo, tmp_path / "derived")
    index.rebuild()
    return index


def test_rebuild_indexes_only_active_annotations(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    active_id = _add(repo, "the budget for embeddings was approved")
    _add(repo, "dismissed note", status=AnnotationStatus.DISMISSED)
    index = _index(tmp_path, repo)

    result = index.search(AnnotationSearchRequest(query="budget"))

    assert result.status is AnnotationSearchStatus.ACCEPTED
    assert [hit.annotation_id for hit in result.hits] == [active_id]


def test_search_matches_prefix_tokens(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "embeddings budget decision recorded")
    index = _index(tmp_path, repo)

    result = index.search(AnnotationSearchRequest(query="embed"))

    assert [hit.annotation_id for hit in result.hits] == [annotation_id]
    assert "[embed" in result.hits[0].snippet.lower()


def test_term_groups_match_any_form_in_a_group(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "решение про бюджету принято")
    index = _index(tmp_path, repo)

    result = index.search(
        AnnotationSearchRequest(
            query="бюджет",
            term_groups=(("бюджет", "бюджету", "бюджета"),),
        )
    )

    assert [hit.annotation_id for hit in result.hits] == [annotation_id]


def test_session_filter_scopes_results(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    here = _add(repo, "shared keyword here", session_id=_SESSION)
    _add(repo, "shared keyword there", session_id=_OTHER_SESSION)
    index = _index(tmp_path, repo)

    result = index.search(
        AnnotationSearchRequest(query="keyword", session_ids=(_SESSION,))
    )

    assert [hit.annotation_id for hit in result.hits] == [here]


def test_source_filter_scopes_results(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    generated = _add(repo, "keyword generated", source=AnnotationSource.GENERATED)
    _add(repo, "keyword edited", source=AnnotationSource.EDITED)
    index = _index(tmp_path, repo)

    result = index.search(
        AnnotationSearchRequest(query="keyword", sources=("generated",))
    )

    assert [hit.annotation_id for hit in result.hits] == [generated]


def test_reproject_updates_one_annotation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "original wording")
    index = _index(tmp_path, repo)
    repo.update_annotation(annotation_id, text="revised keyword wording")

    updated = repo.read_annotation(annotation_id).annotation
    assert updated is not None
    index.reproject_annotation(updated)

    assert index.search(AnnotationSearchRequest(query="original")).hits == ()
    assert [
        hit.annotation_id
        for hit in index.search(AnnotationSearchRequest(query="revised")).hits
    ] == [annotation_id]


def test_reproject_removes_dismissed_annotation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "keyword to dismiss")
    index = _index(tmp_path, repo)
    repo.update_annotation(annotation_id, status=AnnotationStatus.DISMISSED)

    dismissed = repo.read_annotation(annotation_id).annotation
    assert dismissed is not None
    index.reproject_annotation(dismissed)

    assert index.search(AnnotationSearchRequest(query="keyword")).hits == ()


def test_delete_annotation_projection_removes_row(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    annotation_id = _add(repo, "keyword to delete")
    index = _index(tmp_path, repo)

    index.delete_annotation_projection(annotation_id)

    assert index.search(AnnotationSearchRequest(query="keyword")).hits == ()


def test_delete_session_removes_only_that_session(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add(repo, "keyword here", session_id=_SESSION)
    kept = _add(repo, "keyword there", session_id=_OTHER_SESSION)
    index = _index(tmp_path, repo)

    index.delete_session_projection(_SESSION)

    assert [
        hit.annotation_id
        for hit in index.search(AnnotationSearchRequest(query="keyword")).hits
    ] == [kept]


def test_search_is_unavailable_before_rebuild(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    index = AnnotationSearchIndex(repo, tmp_path / "derived")

    result = index.search(AnnotationSearchRequest(query="anything"))

    assert result.status is AnnotationSearchStatus.UNAVAILABLE
