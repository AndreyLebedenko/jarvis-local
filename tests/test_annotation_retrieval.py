from __future__ import annotations

from collections.abc import Sequence

from jarvis.core.config import HistorySemanticSettings
from jarvis.journal import (
    Annotation,
    AnnotationCandidateIdentity,
    AnnotationRead,
    AnnotationReadStatus,
    AnnotationSearchHit,
    AnnotationSearchResult,
    AnnotationSearchStatus,
    AnnotationSemanticCandidate,
    AnnotationSemanticResult,
    AnnotationSemanticStatus,
    AnnotationSource,
    AnnotationStatus,
    AnnotationTarget,
    HistoryCorpusEvent,
    HistoryEventRefsRead,
    HistoryEventRefsReadStatus,
    HistoryRetrievalCandidateKind,
    HistoryRetrievalQuery,
    HistoryRetrievalService,
    HistoryRetrievalSourceMode,
    HistoryRetrievalStatus,
    HistorySearchHit,
    HistorySearchResult,
    HistorySearchStatus,
    JournalEventRef,
    SemanticCandidateResult,
    SemanticCandidateStatus,
)
from jarvis.journal.annotation_search import AnnotationSearchRequest
from jarvis.journal.annotation_semantic import AnnotationSemanticQuery
from jarvis.journal.provenance import (
    ProvenanceSourceKind,
    provenance_descriptor_from_annotation_identity,
)
from jarvis.journal.semantic import (
    CachingQueryEmbeddingProvider,
    SemanticCandidateQuery,
)

_SESSION = "20260801-100000-ab12"


def _settings(*, permissive_gate: bool = False) -> HistorySemanticSettings:
    return HistorySemanticSettings(
        model="fixture",
        query_prefix="q: ",
        passage_prefix="p: ",
        separation=0.0 if permissive_gate else 0.05,
        top_ratio=0.0 if permissive_gate else 0.98,
        dimension=1,
    )


def _annotation(
    annotation_id: str,
    text: str,
    *,
    source: AnnotationSource = AnnotationSource.GENERATED,
    status: AnnotationStatus = AnnotationStatus.ACTIVE,
    start: int | None = None,
    end: int | None = None,
) -> Annotation:
    return Annotation(
        annotation_id=annotation_id,
        target=AnnotationTarget(_SESSION, start, end),
        text=text,
        author="jarvis",
        source=source,
        status=status,
        created_at="2026-08-01T10:00:00+00:00",
        updated_at="2026-08-01T10:00:00+00:00",
    )


def _event(position: int, text: str) -> HistoryCorpusEvent:
    reference = JournalEventRef(_SESSION, position)
    return HistoryCorpusEvent(
        reference,
        "2026-08-01T10:00:00+00:00",
        1785578400.0,
        "user",
        "text",
        text,
        (),
        0,
        None,
        {},
    )


class _FakeCorpusRepository:
    def __init__(
        self,
        *,
        hits: tuple[HistorySearchHit, ...] = (),
        events: tuple[HistoryCorpusEvent, ...] = (),
        search_status: HistorySearchStatus = HistorySearchStatus.ACCEPTED,
    ) -> None:
        self._hits = hits
        self._events = {event.reference: event for event in events}
        self._search_status = search_status

    def search(self, request: object) -> HistorySearchResult:
        del request
        if self._search_status is not HistorySearchStatus.ACCEPTED:
            return HistorySearchResult(self._search_status)
        return HistorySearchResult(HistorySearchStatus.ACCEPTED, self._hits)

    def read_events(
        self, references: tuple[JournalEventRef, ...]
    ) -> HistoryEventRefsRead:
        events = tuple(
            self._events[reference]
            for reference in references
            if reference in self._events
        )
        missing = tuple(
            reference for reference in references if reference not in self._events
        )
        return HistoryEventRefsRead(
            HistoryEventRefsReadStatus.ACCEPTED, events, missing
        )


class _FakeAnnotationLexical:
    def __init__(
        self,
        hits: tuple[AnnotationSearchHit, ...] = (),
        status: AnnotationSearchStatus = AnnotationSearchStatus.ACCEPTED,
    ) -> None:
        self._hits = hits
        self._status = status
        self.requests: list[AnnotationSearchRequest] = []

    def search(self, request: AnnotationSearchRequest) -> AnnotationSearchResult:
        self.requests.append(request)
        if self._status is not AnnotationSearchStatus.ACCEPTED:
            return AnnotationSearchResult(self._status)
        return AnnotationSearchResult(AnnotationSearchStatus.ACCEPTED, self._hits)


class _FakeAnnotationSemantic:
    def __init__(
        self,
        candidates: tuple[AnnotationSemanticCandidate, ...] = (),
        status: AnnotationSemanticStatus = AnnotationSemanticStatus.ACCEPTED,
    ) -> None:
        self._candidates = candidates
        self._status = status
        self.requests: list[AnnotationSemanticQuery] = []

    def query(self, request: AnnotationSemanticQuery) -> AnnotationSemanticResult:
        self.requests.append(request)
        if self._status is not AnnotationSemanticStatus.ACCEPTED:
            return AnnotationSemanticResult(self._status)
        return AnnotationSemanticResult(
            AnnotationSemanticStatus.ACCEPTED, self._candidates
        )


class _FakeAnnotationRead:
    def __init__(self, annotations: dict[str, Annotation]) -> None:
        self._annotations = annotations
        self.read_ids: list[str] = []

    def read_annotation(self, annotation_id: str) -> AnnotationRead:
        self.read_ids.append(annotation_id)
        annotation = self._annotations.get(annotation_id)
        if annotation is None:
            return AnnotationRead(AnnotationReadStatus.NOT_FOUND)
        return AnnotationRead(AnnotationReadStatus.FOUND, annotation)


class _NoSemantic:
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult:
        del request
        return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)


def _annotation_hit(annotation_id: str, *, order_index: int) -> AnnotationSearchHit:
    return AnnotationSearchHit(
        annotation_id=annotation_id,
        session_id=_SESSION,
        timestamp="2026-08-01T10:00:00+00:00",
        source=AnnotationSource.GENERATED.value,
        snippet="...",
        score=-1.0,
        order_index=order_index,
    )


def test_annotation_is_surfaced_as_typed_derived_candidate() -> None:
    annotation = _annotation("ann-1", "Пользователь предпочитает краткие ответы.")
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            (_annotation_hit("ann-1", order_index=0),)
        ),
        annotation_repository=_FakeAnnotationRead({"ann-1": annotation}),
    )

    result = service.retrieve(HistoryRetrievalQuery("краткие ответы", limit=5))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind is HistoryRetrievalCandidateKind.ANNOTATION
    assert candidate.reference is None
    assert candidate.text == annotation.text
    assert candidate.role == "annotation"
    assert candidate.source == AnnotationSource.GENERATED.value
    assert candidate.source_mode is HistoryRetrievalSourceMode.LEXICAL
    assert candidate.annotation == AnnotationCandidateIdentity(
        annotation_id="ann-1",
        session_id=_SESSION,
        source=AnnotationSource.GENERATED.value,
        start_position=None,
        end_position=None,
    )
    assert result.annotation_lexical_count == 1


def test_annotation_range_target_is_preserved_on_candidate() -> None:
    annotation = _annotation("ann-2", "Диапазонная заметка.", start=2, end=5)
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            (_annotation_hit("ann-2", order_index=0),)
        ),
        annotation_repository=_FakeAnnotationRead({"ann-2": annotation}),
    )

    result = service.retrieve(HistoryRetrievalQuery("заметка", limit=5))

    identity = result.candidates[0].annotation
    assert identity is not None
    assert identity.start_position == 2
    assert identity.end_position == 5
    assert identity.is_whole_session is False


def test_annotation_candidate_carries_provenance_descriptor() -> None:
    annotation = _annotation("ann-3", "Заметка с диапазоном.", start=2, end=5)
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            (_annotation_hit("ann-3", order_index=0),)
        ),
        annotation_repository=_FakeAnnotationRead({"ann-3": annotation}),
    )

    result = service.retrieve(HistoryRetrievalQuery("заметка", limit=5))

    candidate = result.candidates[0]
    assert candidate.provenance.source_kind is ProvenanceSourceKind.ANNOTATION
    assert candidate.provenance.is_canonical is False
    assert candidate.provenance.target.event_ref is None
    assert candidate.provenance.target.annotation == AnnotationTarget(_SESSION, 2, 5)
    # Value-level check: equals what the task-1 mapping produces for the same
    # identity. (Call-path proof lives in the serialization sentinel test.)
    assert candidate.provenance == provenance_descriptor_from_annotation_identity(
        candidate.annotation
    )


def test_events_and_annotations_fuse_into_one_ranked_result() -> None:
    event = _event(0, "Сообщение пользователя о насосе.")
    repository = _FakeCorpusRepository(
        hits=(
            HistorySearchHit(
                event.reference,
                event.timestamp,
                "user",
                "text",
                "насос",
                -0.5,
                0,
            ),
        ),
        events=(event,),
    )
    annotation = _annotation("ann-1", "Насос перегрелся после обеда.")
    service = HistoryRetrievalService(
        repository,
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            (_annotation_hit("ann-1", order_index=1),)
        ),
        annotation_repository=_FakeAnnotationRead({"ann-1": annotation}),
    )

    result = service.retrieve(HistoryRetrievalQuery("насос", limit=5))

    kinds = [candidate.kind for candidate in result.candidates]
    assert kinds == [
        HistoryRetrievalCandidateKind.EVENT,
        HistoryRetrievalCandidateKind.ANNOTATION,
    ]
    assert [candidate.combined_rank for candidate in result.candidates] == [1, 2]
    assert result.candidates[0].reference == event.reference
    assert result.candidates[1].annotation is not None


def test_fused_candidate_set_and_order_unchanged_by_provenance_threading() -> None:
    # Additive-only regression at the retrieval boundary itself: threading the
    # provenance descriptor through candidate construction must not filter or
    # reorder the fused result for a fixed fixture. The same lexical hit ranks
    # above the same semantic annotation hit before and after this card.
    event = _event(0, "Сообщение пользователя о насосе.")
    repository = _FakeCorpusRepository(
        hits=(
            HistorySearchHit(
                event.reference,
                event.timestamp,
                "user",
                "text",
                "насос",
                -0.5,
                0,
            ),
        ),
        events=(event,),
    )
    annotation = _annotation("ann-1", "Насос перегрелся после обеда.")
    service = HistoryRetrievalService(
        repository,
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            (_annotation_hit("ann-1", order_index=1),)
        ),
        annotation_repository=_FakeAnnotationRead({"ann-1": annotation}),
    )

    result = service.retrieve(HistoryRetrievalQuery("насос", limit=5))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert result.returned_count == 2
    assert [candidate.kind for candidate in result.candidates] == [
        HistoryRetrievalCandidateKind.EVENT,
        HistoryRetrievalCandidateKind.ANNOTATION,
    ]
    assert [candidate.combined_rank for candidate in result.candidates] == [1, 2]
    assert [candidate.reference for candidate in result.candidates] == [
        event.reference,
        None,
    ]
    assert [
        candidate.annotation.annotation_id
        for candidate in result.candidates
        if candidate.annotation is not None
    ] == ["ann-1"]
    assert all(candidate.provenance is not None for candidate in result.candidates)


def test_annotation_semantic_candidates_are_hydrated_and_gated() -> None:
    annotation = _annotation("ann-sem", "Семантическая заметка о поездке.")
    semantic = _FakeAnnotationSemantic(
        (
            AnnotationSemanticCandidate("ann-sem", _SESSION, 0.9),
            AnnotationSemanticCandidate("ann-low", _SESSION, 0.1),
        )
    )
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(permissive_gate=True),
        annotation_semantic=semantic,
        annotation_repository=_FakeAnnotationRead({"ann-sem": annotation}),
    )

    result = service.retrieve(HistoryRetrievalQuery("поездка", limit=5))

    ids = [
        candidate.annotation.annotation_id
        for candidate in result.candidates
        if candidate.annotation is not None
    ]
    assert ids == ["ann-sem", "ann-low"] or ids == ["ann-sem"]
    top = result.candidates[0]
    assert top.kind is HistoryRetrievalCandidateKind.ANNOTATION
    assert top.source_mode is HistoryRetrievalSourceMode.SEMANTIC
    assert top.semantic_score == 0.9


def test_dismissed_or_deleted_annotation_is_skipped_on_hydration() -> None:
    dismissed = _annotation(
        "ann-dismissed", "Скрытая заметка.", status=AnnotationStatus.DISMISSED
    )
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            (
                _annotation_hit("ann-dismissed", order_index=0),
                _annotation_hit("ann-gone", order_index=1),
            )
        ),
        annotation_repository=_FakeAnnotationRead({"ann-dismissed": dismissed}),
    )

    result = service.retrieve(HistoryRetrievalQuery("заметка", limit=5))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert result.candidates == ()


def test_stale_annotation_does_not_consume_the_result_limit() -> None:
    valid = _annotation("ann-valid", "Актуальная заметка.")
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            (
                _annotation_hit("ann-stale", order_index=0),
                _annotation_hit("ann-valid", order_index=1),
            )
        ),
        annotation_repository=_FakeAnnotationRead({"ann-valid": valid}),
    )

    result = service.retrieve(HistoryRetrievalQuery("заметка", limit=1))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.annotation is not None
    assert candidate.annotation.annotation_id == "ann-valid"
    assert candidate.combined_rank == 1


def test_valid_candidate_beyond_the_first_hydration_chunk_is_still_filled() -> None:
    # More than one 500-candidate chunk, with every stale row ranked above the
    # single valid annotation, which sits past the first chunk boundary. A fixed
    # top-500 window would drop it; ranked chunked hydration must still find it.
    stale_hits = tuple(
        _annotation_hit(f"stale-{index}", order_index=index) for index in range(500)
    )
    valid_hit = _annotation_hit("valid", order_index=500)
    valid = _annotation("valid", "Актуальная заметка в хвосте.")
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical((*stale_hits, valid_hit)),
        annotation_repository=_FakeAnnotationRead({"valid": valid}),
    )

    result = service.retrieve(HistoryRetrievalQuery("заметка", limit=1))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert len(result.candidates) == 1
    assert result.candidates[0].annotation is not None
    assert result.candidates[0].annotation.annotation_id == "valid"


def test_valid_event_fills_slot_left_by_stale_annotation_above_it() -> None:
    event = _event(0, "Актуальное событие.")
    repository = _FakeCorpusRepository(
        hits=(
            HistorySearchHit(
                event.reference, event.timestamp, "user", "text", "e", -0.4, 0
            ),
        ),
        events=(event,),
    )
    service = HistoryRetrievalService(
        repository,
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            # Same lexical rank as the event, so the fusion tiebreak orders this
            # annotation above it - but it is stale and drops on hydration.
            (_annotation_hit("ann-stale", order_index=0),),
        ),
        annotation_repository=_FakeAnnotationRead({}),
    )

    result = service.retrieve(HistoryRetrievalQuery("событие", limit=1))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert len(result.candidates) == 1
    assert result.candidates[0].kind is HistoryRetrievalCandidateKind.EVENT
    assert result.candidates[0].reference == event.reference
    assert result.candidates[0].combined_rank == 1


def test_unavailable_annotation_projections_do_not_fail_event_retrieval() -> None:
    event = _event(0, "Событие пользователя.")
    repository = _FakeCorpusRepository(
        hits=(
            HistorySearchHit(
                event.reference, event.timestamp, "user", "text", "e", -0.5, 0
            ),
        ),
        events=(event,),
    )
    service = HistoryRetrievalService(
        repository,
        _NoSemantic(),
        _settings(),
        annotation_lexical=_FakeAnnotationLexical(
            status=AnnotationSearchStatus.UNAVAILABLE
        ),
        annotation_semantic=_FakeAnnotationSemantic(
            status=AnnotationSemanticStatus.UNAVAILABLE
        ),
        annotation_repository=_FakeAnnotationRead({}),
    )

    result = service.retrieve(HistoryRetrievalQuery("событие", limit=5))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert [candidate.kind for candidate in result.candidates] == [
        HistoryRetrievalCandidateKind.EVENT
    ]
    assert result.annotation_lexical_count == 0
    assert result.annotation_semantic_count == 0


def test_event_roles_and_sources_filters_are_not_forwarded_to_annotations() -> None:
    annotation = _annotation("ann-1", "Заметка.")
    lexical = _FakeAnnotationLexical((_annotation_hit("ann-1", order_index=0),))
    semantic = _FakeAnnotationSemantic(
        (AnnotationSemanticCandidate("ann-1", _SESSION, 0.9),)
    )
    service = HistoryRetrievalService(
        _FakeCorpusRepository(),
        _NoSemantic(),
        _settings(permissive_gate=True),
        annotation_lexical=lexical,
        annotation_semantic=semantic,
        annotation_repository=_FakeAnnotationRead({"ann-1": annotation}),
    )

    result = service.retrieve(
        HistoryRetrievalQuery(
            "заметка",
            limit=5,
            session_ids=(_SESSION,),
            date_from="2026-08-01",
            date_to="2026-08-31",
            roles=("user", "assistant"),
            sources=("text",),
        )
    )

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    lexical_request = lexical.requests[0]
    assert lexical_request.session_ids == (_SESSION,)
    assert lexical_request.date_from == "2026-08-01"
    assert lexical_request.date_to == "2026-08-31"
    assert lexical_request.sources == ()
    semantic_request = semantic.requests[0]
    assert semantic_request.session_ids == (_SESSION,)
    assert semantic_request.sources == ()


def test_annotations_disabled_without_stores_behaves_as_event_only() -> None:
    event = _event(0, "Только событие.")
    repository = _FakeCorpusRepository(
        hits=(
            HistorySearchHit(
                event.reference, event.timestamp, "user", "text", "e", -0.5, 0
            ),
        ),
        events=(event,),
    )
    service = HistoryRetrievalService(repository, _NoSemantic(), _settings())

    result = service.retrieve(HistoryRetrievalQuery("событие", limit=5))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert [candidate.kind for candidate in result.candidates] == [
        HistoryRetrievalCandidateKind.EVENT
    ]


class _CountingEmbedder:
    def __init__(self, dimension: int) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        return [
            tuple(float(len(text)) for _ in range(self._dimension)) for text in texts
        ]


def test_caching_query_embedder_reuses_single_forward_pass() -> None:
    inner = _CountingEmbedder(dimension=1)
    cache = CachingQueryEmbeddingProvider(inner)

    first = cache.embed(["q: поездка"])
    second = cache.embed(["q: поездка"])

    assert first == second
    assert inner.calls == [("q: поездка",)]

    cache.embed(["q: другой запрос"])
    assert len(inner.calls) == 2
