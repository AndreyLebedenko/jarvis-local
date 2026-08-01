"""B2 semantic probe: local embedding retrieval and hybrid fusion.

The retrieval logic here is real and backend-neutral: ``embedding_retrieval``
embeds documents and a query through an injected ``embed_fn``, ranks by cosine
similarity, applies a score threshold, and honours the same session/date scope
as the shipped search. ``hybrid_retrieval`` fuses a lexical (or morphology)
retrieval function with a semantic one, lexical-priority, deduplicated.

The ``embed_fn`` is the only hardware-dependent part. Per the project testing
protocol, a real embedding model (via Ollama or sentence-transformers) is
measured only in the human-run ``measure_semantic`` handoff, never in the pure
suite. For deterministic tests, ``concept_embedder`` is a hand-authored
concept-space fixture: it places each benchmark text on one topical axis, so
paraphrase and synonym queries land on their topic's documents and polysemous
hard negatives stay on their own axis. It is a plumbing-and-target fixture that
sets the ceiling a real model must approximate; it is not a substitute for
measuring one.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from datetime import date

from .corpus import (
    BENCHMARK_DOCUMENTS,
    BENCHMARK_QUERIES,
    BenchmarkDocument,
    BenchmarkQuery,
)
from .harness import RetrievalFunction

EmbedFunction = Callable[[Sequence[str]], list[list[float]]]

_MIN_SIMILARITY = 0.5


def _in_scope(document: BenchmarkDocument, query: BenchmarkQuery) -> bool:
    if query.session_ids and document.session_id not in query.session_ids:
        return False
    document_date = date.fromisoformat(document.timestamp[:10])
    if query.date_from and document_date < date.fromisoformat(query.date_from):
        return False
    return not (query.date_to and document_date > date.fromisoformat(query.date_to))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def embedding_retrieval(
    embed_fn: EmbedFunction,
    documents: tuple[BenchmarkDocument, ...] = BENCHMARK_DOCUMENTS,
    *,
    min_similarity: float = _MIN_SIMILARITY,
    query_prefix: str = "",
    passage_prefix: str = "",
) -> RetrievalFunction:
    """Cosine-similarity retrieval over document embeddings from ``embed_fn``.

    Many embedding models are trained with asymmetric query/passage
    instructions (for example e5's ``query:``/``passage:`` or embeddinggemma's
    task prompt). Without them cosine scores are miscalibrated and an absolute
    threshold does not transfer, so the prefixes are applied here and belong to
    the measured backend, not to the corpus.
    """

    document_vectors = embed_fn(
        [passage_prefix + document.text for document in documents]
    )
    index = list(zip(range(len(documents)), documents, document_vectors, strict=True))

    def retrieve(query: BenchmarkQuery) -> list[str]:
        query_vector = embed_fn([query_prefix + query.text])[0]
        scored: list[tuple[float, int, str]] = []
        for order_index, document, vector in index:
            if not _in_scope(document, query):
                continue
            similarity = _cosine(query_vector, vector)
            if similarity >= min_similarity:
                scored.append((-similarity, order_index, document.doc_id))
        scored.sort()
        return [doc_id for _, _, doc_id in scored]

    return retrieve


def relative_embedding_retrieval(
    embed_fn: EmbedFunction,
    documents: tuple[BenchmarkDocument, ...] = BENCHMARK_DOCUMENTS,
    *,
    query_prefix: str = "",
    passage_prefix: str = "",
    top_ratio: float = 0.98,
    separation: float = 0.01,
) -> RetrievalFunction:
    """Retrieve by a per-query relative gate instead of an absolute threshold.

    Measurement showed an absolute cosine threshold does not transfer across
    models: some models (e5) compress every score into a narrow high band, so a
    fixed threshold returns the distractor for every query. This gate is
    per-query and scale-relative:

    - reject the whole query when the top score does not stand out from the
      median (``top - median < separation``), so a query with no real answer
      (the distractor, or a lexical query the semantic layer cannot serve)
      contributes nothing; and
    - otherwise keep only documents within ``top_ratio`` of the top score.

    This both removes the per-model threshold and stops the semantic layer from
    polluting queries the lexical/morphology side already answers, which the
    naive absolute-threshold union did not.
    """

    document_vectors = embed_fn(
        [passage_prefix + document.text for document in documents]
    )
    index = list(zip(range(len(documents)), documents, document_vectors, strict=True))

    def retrieve(query: BenchmarkQuery) -> list[str]:
        query_vector = embed_fn([query_prefix + query.text])[0]
        scored = [
            (_cosine(query_vector, vector), order_index, document.doc_id)
            for order_index, document, vector in index
            if _in_scope(document, query)
        ]
        if not scored:
            return []
        similarities = [similarity for similarity, _, _ in scored]
        top = max(similarities)
        if top - statistics.median(similarities) < separation:
            return []
        cutoff = top * top_ratio
        kept = sorted(
            (-similarity, order_index, doc_id)
            for similarity, order_index, doc_id in scored
            if similarity >= cutoff
        )
        return [doc_id for _, _, doc_id in kept]

    return retrieve


def hybrid_retrieval(
    lexical: RetrievalFunction, semantic: RetrievalFunction
) -> RetrievalFunction:
    """Fuse lexical/morphology and semantic candidates, lexical-priority."""

    def retrieve(query: BenchmarkQuery) -> list[str]:
        seen: set[str] = set()
        fused: list[str] = []
        for doc_id in [*lexical(query), *semantic(query)]:
            if doc_id not in seen:
                seen.add(doc_id)
                fused.append(doc_id)
        return fused

    return retrieve


# Hand-authored concept axes for the deterministic semantic fixture. Each
# document sits on one topical axis; polysemous hard negatives sit on their own
# axis so a concept-aware retriever does not confuse senses.
_DOCUMENT_CONCEPTS: dict[str, str] = {
    "A0": "bike",
    "A1": "bike",
    "A2": "meeting",
    "A3": "meeting",
    "A4": "weather",
    "HN1": "work_mistake",
    "B0": "order",
    "B1": "order",
    "B2": "payment",
    "B3": "payment",
    "B4": "food",
    "B5": "food",
    "B6": "movie",
    "HN2": "amusement",
    "HN3": "running",
    "HN4": "cancelled",
}

# Only the semantic-tier queries carry a topical concept; every other query
# gets no semantic signal here, so hybrid retrieval relies on its lexical or
# morphology component for them.
_QUERY_CONCEPTS: dict[str, str] = {
    "q-paraphrase-tire": "bike",
    "q-synonym-velik": "bike",
    "q-synonym-beet-soup": "food",
    "q-paraphrase-meeting": "meeting",
    "q-paraphrase-order": "order",
    "q-synonym-payment": "payment",
    "q-synonym-beet-cold-soup": "food",
    "q-synonym-wheel": "bike",
}


def _concept_lookup() -> tuple[list[str], dict[str, int], dict[str, str]]:
    vocabulary = sorted(set(_DOCUMENT_CONCEPTS.values()))
    concept_index = {concept: position for position, concept in enumerate(vocabulary)}
    text_concept: dict[str, str] = {
        document.text: _DOCUMENT_CONCEPTS[document.doc_id]
        for document in BENCHMARK_DOCUMENTS
    }
    for query in BENCHMARK_QUERIES:
        concept = _QUERY_CONCEPTS.get(query.query_id)
        if concept is not None:
            text_concept[query.text] = concept
    return vocabulary, concept_index, text_concept


def concept_embedder() -> EmbedFunction:
    """Clean concept-space fixture: one-hot per concept (no model, no hardware).

    Same concept gives cosine 1.0, different concepts 0.0. Cleanly separable, so
    an absolute threshold works here; it is the baseline plumbing fixture.
    """

    vocabulary, concept_index, text_concept = _concept_lookup()

    def embed(texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * len(vocabulary)
            concept = text_concept.get(text)
            if concept is not None:
                vector[concept_index[concept]] = 1.0
            vectors.append(vector)
        return vectors

    return embed


def compressed_concept_embedder(base: float = 1.0, bump: float = 0.5) -> EmbedFunction:
    """Compressed concept fixture that reproduces the e5 failure mode.

    Every vector shares a large common component, so all cosine scores sit in a
    narrow high band and same-concept scores are only slightly higher. An
    absolute threshold then over-matches (returns the distractor), while a
    per-query relative gate still separates. This fixture exists to test that
    ``relative_embedding_retrieval`` fixes what ``embedding_retrieval`` with a
    fixed threshold cannot.
    """

    vocabulary, concept_index, text_concept = _concept_lookup()

    def embed(texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [base] * len(vocabulary)
            concept = text_concept.get(text)
            if concept is not None:
                vector[concept_index[concept]] = base + bump
            vectors.append(vector)
        return vectors

    return embed
