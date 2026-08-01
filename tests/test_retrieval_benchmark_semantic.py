from __future__ import annotations

from pathlib import Path

import pytest
from retrieval_benchmark import (
    BENCHMARK_QUERIES,
    RetrievalCategory,
    build_benchmark_corpus,
    compressed_concept_embedder,
    concept_embedder,
    current_fts_retrieval,
    embedding_retrieval,
    evaluate_retrieval,
    hybrid_retrieval,
    normalized_retrieval,
    pymorphy3_normalizer,
    relative_embedding_retrieval,
)
from retrieval_benchmark.measure_semantic import _normalize_host


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("0.0.0.0:11434", "http://127.0.0.1:11434"),
        ("localhost:11434", "http://localhost:11434"),
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://localhost:11434/", "http://localhost:11434"),
        ("127.0.0.1:9999", "http://127.0.0.1:9999"),
    ],
)
def test_normalize_host_produces_connectable_url(raw: str, expected: str) -> None:
    assert _normalize_host(raw) == expected


def _recall_by_category(report) -> dict[RetrievalCategory, float | None]:
    return {item.category: item.mean_recall_at_k for item in report.category_reports}


def test_semantic_fixture_closes_tier3_without_hard_negative_false_positives() -> None:
    report = evaluate_retrieval(embedding_retrieval(concept_embedder()))

    print("\n=== B2 semantic fixture (concept space) ===\n" + report.format_table())

    # A concept-aware retriever closes paraphrase and synonym, which no lexical
    # or morphology method reached, and does not confuse polysemous senses.
    assert report.semantic_recall == 1.0
    outcomes = {outcome.query_id: outcome for outcome in report.outcomes}
    for query_id in ("q-paraphrase-tire", "q-synonym-velik", "q-synonym-beet-soup"):
        assert outcomes[query_id].precision_at_k == 1.0, query_id
    # Semantic alone is not a lexical retriever; it earns tier 3, not tier 1.
    assert report.lexical_strength_recall == 0.0
    assert report.distractor_false_positive_rate == 0.0


def test_embedding_retrieval_applies_query_and_passage_prefixes() -> None:
    seen: list[str] = []

    def fake_embed(texts):
        seen.extend(texts)
        return [[1.0] for _ in texts]

    retrieve = embedding_retrieval(fake_embed, query_prefix="Q::", passage_prefix="P::")
    retrieve(BENCHMARK_QUERIES[0])

    assert any(text.startswith("P::") for text in seen)
    assert any(text.startswith("Q::") for text in seen)


def test_absolute_threshold_over_matches_on_a_compressed_space() -> None:
    # Reproduces the measured e5 failure mode: every score sits in a narrow high
    # band, so a fixed absolute threshold returns the distractor for every query.
    report = evaluate_retrieval(
        embedding_retrieval(compressed_concept_embedder(), min_similarity=0.5)
    )
    assert report.distractor_false_positive_rate == 1.0


def test_relative_gate_fixes_the_compressed_space() -> None:
    # The same compressed space, retrieved with the per-query relative gate:
    # the distractor is rejected and the semantic tier is still recalled, with
    # no per-model threshold.
    report = evaluate_retrieval(
        relative_embedding_retrieval(compressed_concept_embedder())
    )
    print("\n=== B2 relative gate on compressed space ===\n" + report.format_table())
    assert report.distractor_false_positive_rate == 0.0
    assert report.semantic_recall == 1.0
    # The gate also keeps semantic silent on lexical queries it cannot serve,
    # so it does not pollute what the lexical side already answers.
    assert report.lexical_strength_recall == 0.0


def test_relative_gate_also_works_on_the_clean_space() -> None:
    report = evaluate_retrieval(relative_embedding_retrieval(concept_embedder()))
    assert report.semantic_recall == 1.0
    assert report.distractor_false_positive_rate == 0.0


def test_semantic_retrieval_is_deterministic() -> None:
    first = evaluate_retrieval(embedding_retrieval(concept_embedder()))
    second = evaluate_retrieval(embedding_retrieval(concept_embedder()))
    assert first.outcomes == second.outcomes


def test_hybrid_over_fts_adds_semantic_without_losing_lexical(tmp_path: Path) -> None:
    repository = build_benchmark_corpus(tmp_path / "corpus")
    hybrid = hybrid_retrieval(
        current_fts_retrieval(repository), embedding_retrieval(concept_embedder())
    )
    report = evaluate_retrieval(hybrid)

    print("\n=== B2 hybrid: FTS + semantic fixture ===\n" + report.format_table())

    # Union keeps the lexical tier from FTS and adds the semantic tier; morphology
    # stays where FTS left it because this hybrid has no morphology component.
    assert report.lexical_strength_recall == 1.0
    assert report.semantic_recall == 1.0
    assert report.distractor_false_positive_rate == 0.0


def test_hybrid_over_morphology_reaches_all_three_tiers(tmp_path: Path) -> None:
    try:
        normalizer = pymorphy3_normalizer()
    except ImportError as exc:
        pytest.skip(f"morphology backend unavailable: {exc}")

    hybrid = hybrid_retrieval(
        normalized_retrieval(normalizer), embedding_retrieval(concept_embedder())
    )
    report = evaluate_retrieval(hybrid)

    print("\n=== B2 hybrid: pymorphy3 + semantic fixture (target ceiling) ===")
    print(report.format_table())

    # The target architecture: morphology-aware lexical plus a semantic layer,
    # fused, reaches every tier. This is the ceiling a real embedding model must
    # approximate; its actual quality is measured in the human-run handoff.
    recall = _recall_by_category(report)
    assert report.lexical_strength_recall == 1.0
    assert report.morphology_recall == 1.0
    assert report.semantic_recall == 1.0
    assert recall[RetrievalCategory.NAME] == 1.0
    assert recall[RetrievalCategory.WORD_FORM] == 1.0
    assert report.distractor_false_positive_rate == 0.0
