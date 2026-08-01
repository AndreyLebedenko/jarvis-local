from __future__ import annotations

from collections.abc import Callable

import pytest
from retrieval_benchmark import (
    RetrievalCategory,
    evaluate_retrieval,
    normalized_retrieval,
    pymorphy3_normalizer,
    snowball_normalizer,
)
from retrieval_benchmark.morphology import Normalizer


def _normalizer_or_skip(factory: Callable[[], Normalizer]) -> Normalizer:
    try:
        return factory()
    except ImportError as exc:  # spike candidate not installed in this env
        pytest.skip(f"morphology backend unavailable: {exc}")


def _name_recall(report) -> float | None:
    for item in report.category_reports:
        if item.category is RetrievalCategory.NAME:
            return item.mean_recall_at_k
    raise AssertionError("name category missing from report")


@pytest.mark.parametrize(
    "name, factory",
    [("pymorphy3", pymorphy3_normalizer), ("snowball", snowball_normalizer)],
)
def test_morphology_baseline_lifts_morphology_not_meaning(
    name: str, factory: Callable[[], Normalizer]
) -> None:
    normalizer = _normalizer_or_skip(factory)
    report = evaluate_retrieval(normalized_retrieval(normalizer))

    # The record for task 8: a cheap local morphology backend closes the
    # word-form and inflected-name gap that pure prefix FTS misses (B0 morphology
    # recall was 0.125), without regressing lexical retrieval, and without
    # touching paraphrase or synonym recall. Meaning is the increment an
    # embedding layer must still earn.
    print(f"\n=== B1 morphology baseline: {name} ===\n" + report.format_table())

    assert report.lexical_strength_recall == 1.0
    assert report.morphology_recall >= 0.7
    assert report.semantic_recall == 0.0


def test_lemmatizer_beats_stemmer_on_name_morphology() -> None:
    pymorphy_norm = _normalizer_or_skip(pymorphy3_normalizer)
    snowball_norm = _normalizer_or_skip(snowball_normalizer)

    pymorphy_report = evaluate_retrieval(normalized_retrieval(pymorphy_norm))
    snowball_report = evaluate_retrieval(normalized_retrieval(snowball_norm))

    # pymorphy3 unifies Андрей/Андрею/Андреем to one lemma; Snowball over-stems
    # (андр vs андре) and reaches only half of the inflected name mentions.
    assert _name_recall(pymorphy_report) == pytest.approx(1.0)
    assert _name_recall(snowball_report) == pytest.approx(0.5)
    assert pymorphy_report.morphology_recall > snowball_report.morphology_recall
