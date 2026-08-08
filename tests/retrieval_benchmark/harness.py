"""Deterministic evaluation harness for the fixed retrieval benchmark.

The harness builds the benchmark corpus through the real journal store and
history corpus repository, so a measured backend is exercised on the shipped
read/search path rather than a re-implementation. A backend is supplied as a
retrieval function mapping a benchmark query to a ranked list of document ids.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jarvis.journal import JournalEvent, JournalEventRef, JournalStore
from jarvis.journal.corpus import (
    HistoryCorpusRepository,
    HistorySearchOrder,
    HistorySearchRequest,
)

from .corpus import (
    BENCHMARK_DOCUMENTS,
    BENCHMARK_QUERIES,
    LEXICAL_STRENGTH_CATEGORIES,
    MORPHOLOGY_CATEGORIES,
    SEMANTIC_CATEGORIES,
    BenchmarkQuery,
    RetrievalCategory,
)

RetrievalFunction = Callable[[BenchmarkQuery], list[str]]

_SEARCH_LIMIT = 50


def document_reference_map(
    documents: tuple[object, ...] = BENCHMARK_DOCUMENTS,
) -> dict[str, JournalEventRef]:
    """Map each benchmark document id to its deterministic event reference.

    Event positions are per-session and 0-based in append order, matching how
    ``JournalStore`` assigns them, so the map is computed without touching the
    store. ``documents`` defaults to the frozen task-11 corpus but accepts any
    document sequence exposing ``doc_id``/``session_id`` (e.g. the task-26
    transcript slice), so a second modality's ids can be resolved the same
    way without colliding with the base map (each slice uses its own session
    ids and letter prefixes).
    """

    positions: dict[str, int] = defaultdict(int)
    references: dict[str, JournalEventRef] = {}
    for document in documents:
        position = positions[document.session_id]
        references[document.doc_id] = JournalEventRef(document.session_id, position)
        positions[document.session_id] = position + 1
    return references


def build_benchmark_corpus(
    root: Path, documents: tuple[object, ...] = BENCHMARK_DOCUMENTS
) -> HistoryCorpusRepository:
    """Append every benchmark document and return a rebuilt corpus repository."""

    store = JournalStore(root / "journal")
    for document in documents:
        store.append(
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
    repository = HistoryCorpusRepository(store, root / "derived")
    repository.rebuild()
    return repository


def current_fts_retrieval(repository: HistoryCorpusRepository) -> RetrievalFunction:
    """Baseline B0: the shipped exact/prefix FTS as a retrieval function."""

    reference_to_id = {
        reference: doc_id for doc_id, reference in document_reference_map().items()
    }

    def retrieve(query: BenchmarkQuery) -> list[str]:
        result = repository.search(
            HistorySearchRequest(
                query=query.text,
                date_from=query.date_from,
                date_to=query.date_to,
                session_ids=query.session_ids,
                limit=_SEARCH_LIMIT,
                order=HistorySearchOrder.RELEVANCE,
            )
        )
        ranked: list[str] = []
        for hit in result.hits:
            doc_id = reference_to_id.get(hit.reference)
            if doc_id is not None:
                ranked.append(doc_id)
        return ranked

    return retrieve


@dataclass(frozen=True)
class QueryOutcome:
    query_id: str
    category: RetrievalCategory
    recall_at_k: float | None
    precision_at_k: float | None
    false_positive_count: int
    returned_count: int
    forbidden_hit: bool


@dataclass(frozen=True)
class CategoryReport:
    category: RetrievalCategory
    mean_recall_at_k: float | None
    query_count: int


@dataclass(frozen=True)
class RetrievalReport:
    outcomes: tuple[QueryOutcome, ...]
    category_reports: tuple[CategoryReport, ...]
    lexical_strength_recall: float
    morphology_recall: float
    semantic_recall: float
    overall_recall: float
    lexical_strength_precision: float
    overall_precision: float
    distractor_false_positive_rate: float

    def format_table(self) -> str:
        lines = [f"{'category':<18}{'mean recall@k':>16}{'queries':>10}"]
        for report in self.category_reports:
            recall = (
                "n/a"
                if report.mean_recall_at_k is None
                else f"{report.mean_recall_at_k:.3f}"
            )
            lines.append(
                f"{report.category.value:<18}{recall:>16}{report.query_count:>10}"
            )
        lines.append("")
        lines.append(
            f"lexical-strength recall@k:    {self.lexical_strength_recall:.3f}"
        )
        lines.append(f"morphology recall@k:          {self.morphology_recall:.3f}")
        lines.append(f"semantic recall@k:            {self.semantic_recall:.3f}")
        lines.append(f"overall recall@k:             {self.overall_recall:.3f}")
        lines.append(
            f"lexical-strength precision@k: {self.lexical_strength_precision:.3f}"
        )
        lines.append(f"overall precision@k:          {self.overall_precision:.3f}")
        lines.append(
            f"distractor FP rate:           {self.distractor_false_positive_rate:.3f}"
        )
        return "\n".join(lines)


def _evaluate_query(query: BenchmarkQuery, retrieved: list[str]) -> QueryOutcome:
    top_k = retrieved[: query.k]
    relevant_in_top = {doc_id for doc_id in top_k if doc_id in query.relevant}
    false_positive_count = sum(1 for doc_id in top_k if doc_id not in query.relevant)
    forbidden_hit = any(doc_id in query.forbidden for doc_id in retrieved)
    recall_at_k = len(relevant_in_top) / len(query.relevant) if query.relevant else None
    precision_at_k = (
        len(relevant_in_top) / len(top_k) if query.relevant and top_k else None
    )
    return QueryOutcome(
        query_id=query.query_id,
        category=query.category,
        recall_at_k=recall_at_k,
        precision_at_k=precision_at_k,
        false_positive_count=false_positive_count,
        returned_count=len(top_k),
        forbidden_hit=forbidden_hit,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_retrieval(
    retrieval_fn: RetrievalFunction,
    queries: tuple[BenchmarkQuery, ...] = BENCHMARK_QUERIES,
) -> RetrievalReport:
    outcomes = tuple(_evaluate_query(query, retrieval_fn(query)) for query in queries)

    recall_by_category: dict[RetrievalCategory, list[float]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.recall_at_k is not None:
            recall_by_category[outcome.category].append(outcome.recall_at_k)

    category_reports = tuple(
        CategoryReport(
            category=category,
            mean_recall_at_k=(
                _mean(recall_by_category[category])
                if recall_by_category[category]
                else None
            ),
            query_count=sum(1 for outcome in outcomes if outcome.category is category),
        )
        for category in RetrievalCategory
    )

    lexical = [
        outcome.recall_at_k
        for outcome in outcomes
        if outcome.recall_at_k is not None
        and outcome.category in LEXICAL_STRENGTH_CATEGORIES
    ]
    morphology = [
        outcome.recall_at_k
        for outcome in outcomes
        if outcome.recall_at_k is not None and outcome.category in MORPHOLOGY_CATEGORIES
    ]
    semantic = [
        outcome.recall_at_k
        for outcome in outcomes
        if outcome.recall_at_k is not None and outcome.category in SEMANTIC_CATEGORIES
    ]
    overall = [
        outcome.recall_at_k for outcome in outcomes if outcome.recall_at_k is not None
    ]
    lexical_precision = [
        outcome.precision_at_k
        for outcome in outcomes
        if outcome.precision_at_k is not None
        and outcome.category in LEXICAL_STRENGTH_CATEGORIES
    ]
    overall_precision = [
        outcome.precision_at_k
        for outcome in outcomes
        if outcome.precision_at_k is not None
    ]
    distractor_outcomes = [
        outcome
        for outcome in outcomes
        if outcome.category is RetrievalCategory.DISTRACTOR
    ]
    distractor_fp_rate = _mean(
        [1.0 if outcome.returned_count else 0.0 for outcome in distractor_outcomes]
    )

    return RetrievalReport(
        outcomes=outcomes,
        category_reports=category_reports,
        lexical_strength_recall=_mean(lexical),
        morphology_recall=_mean(morphology),
        semantic_recall=_mean(semantic),
        overall_recall=_mean(overall),
        lexical_strength_precision=_mean(lexical_precision),
        overall_precision=_mean(overall_precision),
        distractor_false_positive_rate=distractor_fp_rate,
    )
