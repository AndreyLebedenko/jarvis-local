"""Fixed Russian retrieval-quality benchmark for v1.8.0 task 8.

This package is the predeclared benchmark referenced by the hybrid retrieval
design spike (task 8) and reused by the hybrid API quality gate (task 11) and
the retrieval-quality regression (task 26). It is deterministic and runs in the
pure automated suite with no live Ollama, network access, or hardware.

The corpus, relevance labels, metric definitions, and proposed thresholds are
data declared here before any candidate backend is measured. A backend is
evaluated by supplying a retrieval function to `evaluate_retrieval`; the
current shipped exact/prefix FTS is measured as baseline B0 in
`tests/test_retrieval_benchmark.py`.
"""

from .corpus import (
    BENCHMARK_CORPUS_VERSION,
    BENCHMARK_DOCUMENTS,
    BENCHMARK_QUERIES,
    LEXICAL_STRENGTH_CATEGORIES,
    MORPHOLOGY_CATEGORIES,
    RATIFIED_THRESHOLDS,
    SEMANTIC_CATEGORIES,
    BenchmarkDocument,
    BenchmarkQuery,
    RetrievalCategory,
)
from .harness import (
    CategoryReport,
    QueryOutcome,
    RetrievalReport,
    build_benchmark_corpus,
    current_fts_retrieval,
    document_reference_map,
    evaluate_retrieval,
)
from .morphology import (
    normalized_retrieval,
    pymorphy3_normalizer,
    snowball_normalizer,
)
from .semantic import (
    compressed_concept_embedder,
    concept_embedder,
    embedding_retrieval,
    hybrid_retrieval,
    relative_embedding_retrieval,
)

__all__ = [
    "BENCHMARK_CORPUS_VERSION",
    "BENCHMARK_DOCUMENTS",
    "BENCHMARK_QUERIES",
    "LEXICAL_STRENGTH_CATEGORIES",
    "MORPHOLOGY_CATEGORIES",
    "RATIFIED_THRESHOLDS",
    "SEMANTIC_CATEGORIES",
    "BenchmarkDocument",
    "BenchmarkQuery",
    "CategoryReport",
    "QueryOutcome",
    "RetrievalCategory",
    "RetrievalReport",
    "build_benchmark_corpus",
    "compressed_concept_embedder",
    "concept_embedder",
    "current_fts_retrieval",
    "document_reference_map",
    "embedding_retrieval",
    "evaluate_retrieval",
    "hybrid_retrieval",
    "normalized_retrieval",
    "pymorphy3_normalizer",
    "relative_embedding_retrieval",
    "snowball_normalizer",
]
