from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from retrieval_benchmark import (
    BENCHMARK_CORPUS_VERSION,
    BENCHMARK_QUERIES,
    RATIFIED_THRESHOLDS,
    build_benchmark_corpus,
    concept_embedder,
    document_reference_map,
    evaluate_retrieval,
)

from jarvis.core.config import HistorySemanticSettings
from jarvis.journal import (
    HistoryCorpusEvent,
    HistoryEventRefsRead,
    HistoryEventRefsReadStatus,
    HistoryRetrievalFallbackMode,
    HistoryRetrievalQuery,
    HistoryRetrievalService,
    HistoryRetrievalSourceMode,
    HistoryRetrievalStatus,
    HistorySearchHit,
    HistorySearchResult,
    HistorySearchStatus,
    JournalEventRef,
    Pymorphy3Normalizer,
    SemanticCandidateResult,
    SemanticCandidateStatus,
    SemanticPassageIndex,
)
from jarvis.journal.semantic import SemanticCandidateQuery


def test_retrieval_hydrates_lexical_candidates_with_stable_contract(
    tmp_path: Path,
) -> None:
    repository = build_benchmark_corpus(tmp_path / "corpus")
    service = HistoryRetrievalService(
        repository,
        _UnavailableSemanticCandidates(),
        _semantic_settings(dimension=1),
        Pymorphy3Normalizer(),
    )

    result = service.retrieve(HistoryRetrievalQuery("A-2481", limit=2))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert [candidate.reference for candidate in result.candidates] == [
        document_reference_map()["B0"],
        document_reference_map()["B1"],
    ]
    assert all(
        candidate.source_mode is HistoryRetrievalSourceMode.LEXICAL
        for candidate in result.candidates
    )
    assert all(candidate.semantic_score is None for candidate in result.candidates)
    assert [candidate.lexical_rank for candidate in result.candidates] == [1, 2]
    assert all(candidate.text for candidate in result.candidates)
    assert result.fallback_mode is HistoryRetrievalFallbackMode.LEXICAL_BY_UNAVAILABLE
    assert result.elapsed_seconds >= 0.0


def test_retrieval_ranks_are_dense_after_missing_hydration() -> None:
    service = HistoryRetrievalService(
        _MissingHydrationRepository(),
        _UnavailableSemanticCandidates(),
        _semantic_settings(dimension=1),
    )

    result = service.retrieve(HistoryRetrievalQuery("anything", limit=2))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert result.missing_references == (JournalEventRef("20260801-100000-ms01", 0),)
    assert [candidate.combined_rank for candidate in result.candidates] == [1]
    assert result.candidates[0].reference == JournalEventRef("20260801-100100-fd01", 0)
    assert result.candidates[0].truncated is False


def test_retrieval_fuses_semantic_and_lexical_candidates(tmp_path: Path) -> None:
    repository, semantic = _build_semantic_benchmark(tmp_path)
    service = HistoryRetrievalService(
        repository,
        semantic,
        _semantic_settings(dimension=_concept_dimension()),
        Pymorphy3Normalizer(),
    )

    result = service.retrieve(
        HistoryRetrievalQuery("как заклеить спущенную шину", limit=5)
    )

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert [candidate.reference for candidate in result.candidates] == [
        document_reference_map()["A0"],
        document_reference_map()["A1"],
    ]
    assert all(
        candidate.source_mode is HistoryRetrievalSourceMode.SEMANTIC
        for candidate in result.candidates
    )
    assert all(candidate.semantic_score == 1.0 for candidate in result.candidates)
    assert all(candidate.lexical_rank is None for candidate in result.candidates)
    assert result.fallback_mode is HistoryRetrievalFallbackMode.FULL_HYBRID


def test_retrieval_falls_back_to_lexical_when_semantic_times_out(
    tmp_path: Path,
) -> None:
    repository = build_benchmark_corpus(tmp_path / "corpus")
    service = HistoryRetrievalService(
        repository,
        _TimeoutSemanticCandidates(),
        _semantic_settings(dimension=1),
        Pymorphy3Normalizer(),
    )

    result = service.retrieve(HistoryRetrievalQuery("A-2481", limit=2))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert [candidate.reference for candidate in result.candidates] == [
        document_reference_map()["B0"],
        document_reference_map()["B1"],
    ]
    assert result.fallback_mode is HistoryRetrievalFallbackMode.LEXICAL_BY_TIMEOUT
    assert result.elapsed_seconds >= 0.0


def test_relative_gate_keeps_semantic_silent_on_distractor_query(
    tmp_path: Path,
) -> None:
    repository, semantic = _build_semantic_benchmark(tmp_path)
    service = HistoryRetrievalService(
        repository,
        semantic,
        _semantic_settings(dimension=_concept_dimension()),
        Pymorphy3Normalizer(),
    )

    result = service.retrieve(HistoryRetrievalQuery("инвестиции в криптовалюту"))

    assert result.status is HistoryRetrievalStatus.ACCEPTED
    assert result.candidates == ()
    assert result.semantic_count == 0
    assert result.fallback_mode is HistoryRetrievalFallbackMode.FULL_HYBRID


def test_filters_compose_with_lexical_and_semantic_candidates(tmp_path: Path) -> None:
    repository, semantic = _build_semantic_benchmark(tmp_path)
    service = HistoryRetrievalService(
        repository,
        semantic,
        _semantic_settings(dimension=_concept_dimension()),
        Pymorphy3Normalizer(),
    )

    lexical = service.retrieve(
        HistoryRetrievalQuery(
            "велосип",
            session_ids=("20260520-160000-bb02",),
            limit=5,
        )
    )
    semantic_result = service.retrieve(
        HistoryRetrievalQuery(
            "когда привезут мою покупку",
            date_from="2026-05-01",
            date_to="2026-05-31",
            limit=5,
        )
    )

    assert [candidate.reference for candidate in lexical.candidates] == [
        document_reference_map()["B2"]
    ]
    assert [candidate.reference for candidate in semantic_result.candidates] == [
        document_reference_map()["B0"],
        document_reference_map()["B1"],
    ]
    assert semantic_result.fallback_mode is HistoryRetrievalFallbackMode.FULL_HYBRID


def test_hybrid_domain_api_passes_ratified_fixture_quality_gate(
    tmp_path: Path,
) -> None:
    repository, semantic = _build_semantic_benchmark(tmp_path)
    service = HistoryRetrievalService(
        repository,
        semantic,
        _semantic_settings(dimension=_concept_dimension()),
        Pymorphy3Normalizer(),
    )
    reference_to_id = {
        reference: doc_id for doc_id, reference in document_reference_map().items()
    }

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
        return [
            reference_to_id[candidate.reference]
            for candidate in result.candidates
            if candidate.reference in reference_to_id
        ]

    report = evaluate_retrieval(retrieve)

    print(
        f"\n=== Task 11 hybrid domain API fixture ({BENCHMARK_CORPUS_VERSION}) ===\n"
        + report.format_table()
    )
    assert (
        report.lexical_strength_recall
        >= RATIFIED_THRESHOLDS["lexical_strength_recall_at_k"]
    )
    assert report.morphology_recall >= RATIFIED_THRESHOLDS["morphology_recall_at_k"]
    assert report.semantic_recall >= RATIFIED_THRESHOLDS["semantic_recall_at_k"]
    assert report.overall_recall >= RATIFIED_THRESHOLDS["overall_recall_at_k"]
    assert report.overall_precision >= RATIFIED_THRESHOLDS["overall_precision_at_k"]
    assert (
        report.distractor_false_positive_rate
        <= RATIFIED_THRESHOLDS["max_distractor_false_positive_rate"]
    )
    assert all(not outcome.forbidden_hit for outcome in report.outcomes)


def _build_semantic_benchmark(
    tmp_path: Path,
):
    repository = build_benchmark_corpus(tmp_path / "corpus")
    semantic = SemanticPassageIndex(
        repository,
        tmp_path / "corpus" / "derived",
        _semantic_settings(dimension=_concept_dimension()),
        _ConceptEmbedder(),
    )
    semantic.rebuild()
    return repository, semantic


def _semantic_settings(*, dimension: int) -> HistorySemanticSettings:
    return HistorySemanticSettings(
        model="concept-fixture",
        query_prefix="",
        passage_prefix="",
        separation=0.05,
        top_ratio=0.98,
        dimension=dimension,
    )


def _concept_dimension() -> int:
    return len(concept_embedder()([BENCHMARK_QUERIES[0].text])[0])


class _ConceptEmbedder:
    def __init__(self) -> None:
        self._embed = concept_embedder()

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        return [tuple(vector) for vector in self._embed(texts)]


class _UnavailableSemanticCandidates:
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult:
        del request
        return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)


class _TimeoutSemanticCandidates:
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult:
        del request
        return SemanticCandidateResult(SemanticCandidateStatus.TIMEOUT)


class _MissingHydrationRepository:
    def search(self, request: object) -> HistorySearchResult:
        del request
        return HistorySearchResult(
            HistorySearchStatus.ACCEPTED,
            (
                HistorySearchHit(
                    JournalEventRef("20260801-100000-ms01", 0),
                    "2026-08-01T10:00:00+00:00",
                    "user",
                    "text",
                    "missing",
                    -1.0,
                    0,
                ),
                HistorySearchHit(
                    JournalEventRef("20260801-100100-fd01", 0),
                    "2026-08-01T10:01:00+00:00",
                    "user",
                    "text",
                    "found",
                    -0.5,
                    1,
                ),
            ),
        )

    def read_events(
        self, references: tuple[JournalEventRef, ...]
    ) -> HistoryEventRefsRead:
        assert references == (
            JournalEventRef("20260801-100000-ms01", 0),
            JournalEventRef("20260801-100100-fd01", 0),
        )
        return HistoryEventRefsRead(
            HistoryEventRefsReadStatus.ACCEPTED,
            (
                HistoryCorpusEvent(
                    JournalEventRef("20260801-100100-fd01", 0),
                    "2026-08-01T10:01:00+00:00",
                    1785578460.0,
                    "user",
                    "text",
                    "found text",
                    (),
                    0,
                    None,
                    {},
                ),
            ),
            (JournalEventRef("20260801-100000-ms01", 0),),
        )
