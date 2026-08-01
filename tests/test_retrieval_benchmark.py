from __future__ import annotations

from pathlib import Path

import pytest
from retrieval_benchmark import (
    BENCHMARK_DOCUMENTS,
    BENCHMARK_QUERIES,
    LEXICAL_STRENGTH_CATEGORIES,
    MORPHOLOGY_CATEGORIES,
    SEMANTIC_CATEGORIES,
    RetrievalCategory,
    build_benchmark_corpus,
    current_fts_retrieval,
    document_reference_map,
    evaluate_retrieval,
)

_DOCUMENT_IDS = {document.doc_id for document in BENCHMARK_DOCUMENTS}


def test_benchmark_labels_reference_existing_documents() -> None:
    for query in BENCHMARK_QUERIES:
        assert query.relevant <= _DOCUMENT_IDS, query.query_id
        assert query.forbidden <= _DOCUMENT_IDS, query.query_id


def test_benchmark_query_ids_are_unique() -> None:
    query_ids = [query.query_id for query in BENCHMARK_QUERIES]
    assert len(query_ids) == len(set(query_ids))


def test_benchmark_covers_every_category() -> None:
    used = {query.category for query in BENCHMARK_QUERIES}
    assert used == set(RetrievalCategory)
    tiers = [LEXICAL_STRENGTH_CATEGORIES, MORPHOLOGY_CATEGORIES, SEMANTIC_CATEGORIES]
    for first_index, first in enumerate(tiers):
        for second in tiers[first_index + 1 :]:
            assert first.isdisjoint(second)
    tiered = LEXICAL_STRENGTH_CATEGORIES | MORPHOLOGY_CATEGORIES | SEMANTIC_CATEGORIES
    assert tiered == set(RetrievalCategory) - {RetrievalCategory.DISTRACTOR}


def test_document_reference_positions_are_zero_based_per_session() -> None:
    references = document_reference_map()
    assert references["A0"].event_position == 0
    assert references["A4"].event_position == 4
    assert references["B0"].event_position == 0
    assert references["B6"].event_position == 6


def test_current_fts_baseline_is_deterministic(tmp_path: Path) -> None:
    first = evaluate_retrieval(
        current_fts_retrieval(build_benchmark_corpus(tmp_path / "first"))
    )
    second = evaluate_retrieval(
        current_fts_retrieval(build_benchmark_corpus(tmp_path / "second"))
    )
    assert first.outcomes == second.outcomes


def test_current_fts_baseline_locks_lexical_strength_and_exposes_gap(
    tmp_path: Path,
) -> None:
    repository = build_benchmark_corpus(tmp_path / "corpus")
    report = evaluate_retrieval(current_fts_retrieval(repository))

    # The record for task 8: the shipped exact/prefix FTS fully serves literal
    # lexical retrieval, only half-serves inflected names, and returns nothing
    # for word forms, paraphrase, or synonym. This is the measured motivation
    # for a morphology-aware baseline and a semantic layer.
    print("\n" + report.format_table())

    assert report.lexical_strength_recall == 1.0
    assert report.morphology_recall == pytest.approx(0.125)
    assert report.semantic_recall == 0.0
    assert report.distractor_false_positive_rate == 0.0
    assert report.overall_recall == pytest.approx(7.5 / 19)
    assert not any(outcome.forbidden_hit for outcome in report.outcomes)

    # Hard negatives bite: lexical retrieval cannot disambiguate polysemy, so
    # its precision is below 1.0 even on the categories it recalls perfectly.
    # A disambiguating backend must beat this without losing lexical recall.
    assert report.lexical_strength_precision < 1.0


def test_current_fts_baseline_per_category_expectations(tmp_path: Path) -> None:
    repository = build_benchmark_corpus(tmp_path / "corpus")
    report = evaluate_retrieval(current_fts_retrieval(repository))
    recall_by_category = {
        item.category: item.mean_recall_at_k for item in report.category_reports
    }

    for category in LEXICAL_STRENGTH_CATEGORIES:
        assert recall_by_category[category] == 1.0, category.value
    # Inflected name is only half-reached by prefix FTS; word forms not at all.
    assert recall_by_category[RetrievalCategory.NAME] == pytest.approx(0.5)
    assert recall_by_category[RetrievalCategory.WORD_FORM] == 0.0
    for category in SEMANTIC_CATEGORIES:
        assert recall_by_category[category] == 0.0, category.value


def test_documents_are_text_native_only() -> None:
    # v1.8.0 scope: native conversation text only. Transcript/annotation
    # modalities enter in v1.8.1 (card 26) as separate labeled slices.
    for document in BENCHMARK_DOCUMENTS:
        assert document.role in {"user", "assistant"}, document.doc_id
        assert document.source in {"text", "assistant"}, document.doc_id


def test_hard_negatives_are_unlabeled_and_bite_lexical_precision(
    tmp_path: Path,
) -> None:
    hard_negatives = {
        document.doc_id
        for document in BENCHMARK_DOCUMENTS
        if document.doc_id.startswith("HN")
    }
    assert len(hard_negatives) >= 4
    for query in BENCHMARK_QUERIES:
        assert hard_negatives.isdisjoint(query.relevant), query.query_id

    report = evaluate_retrieval(
        current_fts_retrieval(build_benchmark_corpus(tmp_path / "corpus"))
    )
    outcomes = {outcome.query_id: outcome for outcome in report.outcomes}
    # Each hard negative is a genuine false positive for its polysemous query
    # under the current lexical backend.
    for query_id in ("q-exact-prokol", "q-number-5000", "q-wordform-koleso"):
        assert outcomes[query_id].false_positive_count >= 1, query_id
