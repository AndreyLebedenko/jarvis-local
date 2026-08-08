"""Task v1.8.0-26: retrieval-quality regression after transcripts/annotations.

Reruns the fixed task-11 benchmark (unchanged: ``BENCHMARK_QUERIES``,
``RATIFIED_THRESHOLDS``) plus two new labeled slices - transcript-derived text
(task v1.8.0-18..20) and annotation-derived text (task v1.8.0-21..23) - through
one shared ``HistoryRetrievalService``, deterministically and without live
Ollama, network access, or hardware (a concept-space fixture embedder stands in
for the real backend, per the project testing protocol).

This also carries the deferred check from task v1.8.0-23: a log-backed repro
of the PUT-edit/reprojection race described in
``tasks/bug_reports/2026-08-08-edited-annotation-recall-miss-in-new-context.md``.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from retrieval_benchmark import (
    BENCHMARK_CORPUS_VERSION,
    BENCHMARK_DOCUMENTS,
    BENCHMARK_QUERIES,
    RATIFIED_THRESHOLDS,
    document_reference_map,
    evaluate_retrieval,
)
from retrieval_benchmark.multimodal_corpus import (
    ANNOTATION_BENCHMARK_QUERIES,
    BENCHMARK_ANNOTATIONS,
    MULTIMODAL_CORPUS_VERSION,
    TEXT_CONCEPTS,
    TRANSCRIPT_BENCHMARK_DOCUMENTS,
    TRANSCRIPT_BENCHMARK_QUERIES,
)
from retrieval_benchmark.semantic import extended_concept_embedder

from jarvis.core.bus import EventBus
from jarvis.core.config import HistorySemanticSettings
from jarvis.journal import (
    Annotation,
    AnnotationOverlayChanged,
    AnnotationOverlayRepository,
    AnnotationSearchIndex,
    AnnotationSemanticIndex,
    AnnotationSource,
    AnnotationTarget,
    HistoryCorpusRepository,
    HistoryProjectionLifecycle,
    HistoryRetrievalCandidateKind,
    HistoryRetrievalQuery,
    HistoryRetrievalService,
    HistoryRetrievalStatus,
    JournalEvent,
    JournalStore,
    JournalStoreEventReferenceResolver,
    Pymorphy3Normalizer,
    SemanticCandidateResult,
    SemanticCandidateStatus,
    SemanticPassageIndex,
)
from jarvis.journal.semantic import SemanticCandidateQuery
from jarvis.journal.transcript import (
    TranscriptOverlayRepository,
    TranscriptOverlayTextResolver,
    TranscriptSource,
)

pytestmark = pytest.mark.filterwarnings("ignore")


def _settings(*, dimension: int) -> HistorySemanticSettings:
    return HistorySemanticSettings(
        model="concept-fixture",
        query_prefix="",
        passage_prefix="",
        separation=0.05,
        top_ratio=0.98,
        dimension=dimension,
    )


class _ConceptEmbedder:
    """Wraps the shared extended concept-space fixture for the ``embed`` protocol."""

    def __init__(self) -> None:
        self._embed = extended_concept_embedder(TEXT_CONCEPTS)

    def embed(self, texts):
        return [tuple(vector) for vector in self._embed(list(texts))]


def _dimension() -> int:
    embed = extended_concept_embedder(TEXT_CONCEPTS)
    return len(embed([BENCHMARK_QUERIES[0].text])[0])


class _Corpus:
    """Everything the regression benchmark builds once: store, corpus,
    transcripts, annotations, and every lexical/semantic index, deterministic
    and fully synchronous (no lifecycle/bus needed for a fixed corpus built
    once)."""

    def __init__(self, root: Path) -> None:
        self.store = JournalStore(root / "journal")
        for document in BENCHMARK_DOCUMENTS:
            self.store.append(
                JournalEvent(
                    session_id=document.session_id,
                    timestamp=document.timestamp,
                    source=document.source,
                    role=document.role,
                    text=document.text,
                    media=(),
                    transcript=None,
                    metadata={},
                )
            )
        for document in TRANSCRIPT_BENCHMARK_DOCUMENTS:
            self.store.append(
                JournalEvent(
                    session_id=document.session_id,
                    timestamp=document.timestamp,
                    source=document.source,
                    role=document.role,
                    text="" if document.is_transcript else document.text,
                    media=(),
                    transcript=None,
                    metadata={},
                )
            )

        resolver = JournalStoreEventReferenceResolver(self.store)
        self.transcripts = TranscriptOverlayRepository(root / "derived", resolver)
        self.transcript_ids = document_reference_map(TRANSCRIPT_BENCHMARK_DOCUMENTS)
        for document in TRANSCRIPT_BENCHMARK_DOCUMENTS:
            if document.is_transcript:
                result = self.transcripts.upsert_transcript(
                    self.transcript_ids[document.doc_id],
                    document.text,
                    TranscriptSource.GENERATED,
                )
                assert result.accepted, result.status
        transcript_resolver = TranscriptOverlayTextResolver(self.transcripts)

        self.corpus = HistoryCorpusRepository(
            self.store, root / "derived", transcript_resolver
        )
        self.corpus.rebuild()

        dimension = _dimension()
        settings = _settings(dimension=dimension)

        self.semantic = SemanticPassageIndex(
            self.corpus,
            root / "derived",
            settings,
            _ConceptEmbedder(),
            transcripts=transcript_resolver,
        )
        self.semantic.rebuild()

        self.annotations = AnnotationOverlayRepository(root / "derived", resolver)
        self.annotation_ids: dict[str, str] = {}
        for annotation in BENCHMARK_ANNOTATIONS:
            target = AnnotationTarget(
                annotation.session_id,
                annotation.start_position,
                annotation.end_position,
            )
            result = self.annotations.add_annotation(
                target, annotation.text, annotation.author, annotation.source
            )
            assert result.accepted, result.status
            assert result.annotation_id is not None
            self.annotation_ids[annotation.label] = result.annotation_id

        self.annotation_lexical = AnnotationSearchIndex(
            self.annotations, root / "derived"
        )
        self.annotation_lexical.rebuild()
        self.annotation_semantic = AnnotationSemanticIndex(
            self.annotations, root / "derived", settings, _ConceptEmbedder()
        )
        self.annotation_semantic.rebuild()

    def id_map(self) -> dict[object, str]:
        merged: dict[object, str] = {}
        for doc_id, reference in document_reference_map().items():
            merged[reference] = doc_id
        for doc_id, reference in self.transcript_ids.items():
            merged[reference] = doc_id
        for label, annotation_id in self.annotation_ids.items():
            merged[annotation_id] = label
        return merged

    def service(
        self,
        *,
        event_semantic_enabled: bool = True,
        annotation_semantic_enabled: bool = True,
    ) -> HistoryRetrievalService:
        dimension = _dimension()
        settings = _settings(dimension=dimension)
        event_semantic: object = self.semantic
        if not event_semantic_enabled:
            event_semantic = _UnavailableSemanticCandidates()
        return HistoryRetrievalService(
            self.corpus,
            event_semantic,
            settings,
            Pymorphy3Normalizer(),
            annotation_lexical=self.annotation_lexical,
            annotation_semantic=(
                self.annotation_semantic if annotation_semantic_enabled else None
            ),
            annotation_repository=self.annotations,
        )


class _UnavailableSemanticCandidates:
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult:
        del request
        return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)


def _retrieval_function(service: HistoryRetrievalService, id_map: dict[object, str]):
    def retrieve(query) -> list[str]:
        result = service.retrieve(
            HistoryRetrievalQuery(
                query.text,
                limit=query.k,
                session_ids=query.session_ids,
                date_from=query.date_from,
                date_to=query.date_to,
            )
        )
        ids: list[str] = []
        for candidate in result.candidates:
            if candidate.kind is HistoryRetrievalCandidateKind.EVENT:
                mapped = id_map.get(candidate.reference)
            else:
                assert candidate.annotation is not None
                mapped = id_map.get(candidate.annotation.annotation_id)
            if mapped is not None:
                ids.append(mapped)
        return ids

    return retrieve


def _assert_ratified(report, *, label: str) -> None:
    print(f"\n=== {label} ({MULTIMODAL_CORPUS_VERSION}) ===\n" + report.format_table())
    assert (
        report.lexical_strength_recall
        >= RATIFIED_THRESHOLDS["lexical_strength_recall_at_k"]
    ), label
    assert report.morphology_recall >= RATIFIED_THRESHOLDS["morphology_recall_at_k"], (
        label
    )
    assert report.semantic_recall >= RATIFIED_THRESHOLDS["semantic_recall_at_k"], label
    assert report.overall_recall >= RATIFIED_THRESHOLDS["overall_recall_at_k"], label
    assert report.overall_precision >= RATIFIED_THRESHOLDS["overall_precision_at_k"], (
        label
    )
    assert (
        report.distractor_false_positive_rate
        <= RATIFIED_THRESHOLDS["max_distractor_false_positive_rate"]
    ), label
    assert all(not outcome.forbidden_hit for outcome in report.outcomes), label


def test_base_corpus_still_meets_ratified_thresholds_with_slices_added(
    tmp_path: Path,
) -> None:
    """The frozen task-11 corpus/queries must not regress once transcript and
    annotation text join the same corpus and the same retrieval service."""

    corpus = _Corpus(tmp_path)
    service = corpus.service()
    retrieve = _retrieval_function(service, corpus.id_map())

    report = evaluate_retrieval(retrieve)

    _assert_ratified(report, label=f"base corpus {BENCHMARK_CORPUS_VERSION}")


def test_transcript_slice_meets_ratified_thresholds(tmp_path: Path) -> None:
    corpus = _Corpus(tmp_path)
    service = corpus.service()
    retrieve = _retrieval_function(service, corpus.id_map())

    report = evaluate_retrieval(retrieve, TRANSCRIPT_BENCHMARK_QUERIES)

    _assert_ratified(report, label="transcript slice")


def test_annotation_slice_meets_ratified_thresholds(tmp_path: Path) -> None:
    corpus = _Corpus(tmp_path)
    service = corpus.service()
    retrieve = _retrieval_function(service, corpus.id_map())

    report = evaluate_retrieval(retrieve, ANNOTATION_BENCHMARK_QUERIES)

    _assert_ratified(report, label="annotation slice")


def test_annotation_candidates_are_typed_derived_data_not_raw_events(
    tmp_path: Path,
) -> None:
    corpus = _Corpus(tmp_path)
    service = corpus.service()

    result = service.retrieve(HistoryRetrievalQuery("шлем", limit=5))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert any(
        candidate.kind is HistoryRetrievalCandidateKind.ANNOTATION
        and candidate.annotation is not None
        and candidate.annotation.annotation_id == corpus.annotation_ids["ANN-A"]
        for candidate in result.candidates
    )


def test_exact_and_identifier_fallback_works_for_transcript_and_annotation_text(
    tmp_path: Path,
) -> None:
    """Confirms exact/prefix fallback still works for literal cases (task-26
    requirement) on both new modalities: with the semantic layer unavailable
    on both the event and annotation sides, lexical-strength and morphology
    queries over transcript- and annotation-derived text still resolve."""

    corpus = _Corpus(tmp_path)
    service = corpus.service(
        event_semantic_enabled=False, annotation_semantic_enabled=False
    )
    id_map = corpus.id_map()
    retrieve = _retrieval_function(service, id_map)

    literal_transcript = [
        query
        for query in TRANSCRIPT_BENCHMARK_QUERIES
        if query.category.value in {"exact_term", "prefix", "identifier", "word_form"}
    ]
    literal_annotation = [
        query
        for query in ANNOTATION_BENCHMARK_QUERIES
        if query.category.value in {"exact_term", "prefix", "identifier", "word_form"}
    ]
    assert literal_transcript and literal_annotation

    for query in [*literal_transcript, *literal_annotation]:
        retrieved = set(retrieve(query)[: query.k])
        assert query.relevant <= retrieved, (query.query_id, retrieved)


# --- Deferred check from task v1.8.0-23: race vs. ranking-miss repro --------


class _BlockableAnnotationSearchIndex:
    """Wraps a real ``AnnotationSearchIndex`` and can block its next
    ``reproject_annotation`` call until the test releases a gate - the same
    technique ``test_annotation_projection_lifecycle.py`` uses, applied to the
    production index instead of a recording fake, so the repro exercises the
    real lexical/semantic reindex path (including its SQLite writes)."""

    def __init__(self, inner: AnnotationSearchIndex) -> None:
        self._inner = inner
        self.name = inner.name
        self._gate: threading.Event | None = None
        self.entered = threading.Event()

    def block_next_reprojection(self) -> threading.Event:
        gate = threading.Event()
        self._gate = gate
        return gate

    def startup_rebuild(self) -> None:
        self._inner.startup_rebuild()

    def reproject_annotation(self, annotation: Annotation) -> None:
        gate = self._gate
        self._gate = None
        if gate is not None:
            self.entered.set()
            gate.wait(5)
        self._inner.reproject_annotation(annotation)

    def delete_annotation_projection(self, annotation_id: str) -> None:
        self._inner.delete_annotation_projection(annotation_id)

    def delete_session_projection(self, session_id: str) -> None:
        self._inner.delete_session_projection(session_id)


@pytest.mark.asyncio
async def test_annotation_edit_reprojection_race_is_real_and_bounded_by_wait_for_idle(
    tmp_path: Path,
) -> None:
    """Deterministic repro for the deferred check in
    tasks/bug_reports/2026-08-08-edited-annotation-recall-miss-in-new-context.md.

    Confirms explanation 1 (the PUT-edit/reprojection race) is structurally
    real today: a retrieval query issued in the window between
    ``AnnotationOverlayChanged`` publish and reprojection completion can miss
    an edit that was just saved, and ``HistoryProjectionLifecycle.wait_for_idle()``
    is the deterministic boundary of that window.
    """

    corpus = _Corpus(tmp_path)
    blockable = _BlockableAnnotationSearchIndex(corpus.annotation_lexical)
    bus = EventBus()
    lifecycle = HistoryProjectionLifecycle(
        bus,
        projections=(),
        semantic_projection=_NoopSemanticProjection(),
        annotation_projections=(blockable, corpus.annotation_semantic),
        annotation_source=corpus.annotations,
    )
    await lifecycle.start()
    try:
        service = corpus.service()
        annotation_id = corpus.annotation_ids["ANN-B"]

        old_hit = service.retrieve(HistoryRetrievalQuery("нехватки", limit=5))
        assert any(
            c.kind is HistoryRetrievalCandidateKind.ANNOTATION
            and c.annotation is not None
            and c.annotation.annotation_id == annotation_id
            for c in old_hit.candidates
        )

        gate = blockable.block_next_reprojection()
        new_text = (
            "Уточнение: доставка заказа A-2481 задерживается из-за перебоев "
            "с поставками уплотнителей."
        )
        update = corpus.annotations.update_annotation(
            annotation_id, text=new_text, source=AnnotationSource.EDITED
        )
        assert update.accepted

        await bus.publish(
            AnnotationOverlayChanged,
            AnnotationOverlayChanged("20260520-160000-bb02", annotation_id),
        )

        # RACE WINDOW: reprojection is blocked mid-write (gate not yet set).
        # A query issued here mirrors "fresh context queries shortly after
        # save" from the bug report.
        assert await asyncio.to_thread(blockable.entered.wait, 5)
        during_window = service.retrieve(HistoryRetrievalQuery("перебоев", limit=5))
        assert not any(
            c.kind is HistoryRetrievalCandidateKind.ANNOTATION
            and c.annotation is not None
            and c.annotation.annotation_id == annotation_id
            for c in during_window.candidates
        ), "edited text was searchable before reprojection completed"

        gate.set()
        await lifecycle.wait_for_idle()

        after_idle = service.retrieve(HistoryRetrievalQuery("перебоев", limit=5))
        assert any(
            c.kind is HistoryRetrievalCandidateKind.ANNOTATION
            and c.annotation is not None
            and c.annotation.annotation_id == annotation_id
            for c in after_idle.candidates
        ), "edited text still not searchable after wait_for_idle()"
    finally:
        await lifecycle.close()


class _NoopSemanticProjection:
    """Stands in for the event semantic projection: this repro test only
    exercises the annotation reprojection path, so the lifecycle's other
    startup/delete hooks just need to be no-ops."""

    def rebuild_if_backend_changed(self) -> None:
        pass

    def delete_session_projection(self, session_id: str) -> None:
        del session_id
