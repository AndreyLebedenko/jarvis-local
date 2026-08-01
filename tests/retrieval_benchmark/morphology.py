"""B1 morphology baseline: lemmatized/stemmed lexical retrieval.

This models a morphology-aware lexical FTS. A document matches a query token
when the token's normalized form equals a document token's normalized form
(morphology), or a raw document token starts with the raw query token (the
prefix strength the shipped FTS already has, kept for bare-prefix queries that
normalization would mangle). All query tokens must match (AND), matching the
shipped search semantics.

Two candidate morphology backends are measured: a pymorphy3 lemmatizer and a
Snowball stemmer. Neither adds a per-turn model forward pass, VRAM, or network
dependency; both run as deterministic local CPU text normalization. The backend
packages are spike candidates and are intentionally not added to
``requirements.txt`` until one is selected; the probe tests skip when a backend
is not installed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from datetime import date

from .corpus import BENCHMARK_DOCUMENTS, BenchmarkDocument, BenchmarkQuery
from .harness import RetrievalFunction

Normalizer = Callable[[str], str]

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def pymorphy3_normalizer() -> Normalizer:
    """Lemmatizer normalizer. Raises ImportError if pymorphy3 is absent."""

    import pymorphy3

    analyzer = pymorphy3.MorphAnalyzer()
    cache: dict[str, str] = {}

    def normalize(token: str) -> str:
        folded = token.casefold()
        cached = cache.get(folded)
        if cached is None:
            cached = analyzer.parse(folded)[0].normal_form
            cache[folded] = cached
        return cached

    return normalize


def snowball_normalizer() -> Normalizer:
    """Stemmer normalizer. Raises ImportError if snowballstemmer is absent."""

    import snowballstemmer

    stemmer = snowballstemmer.stemmer("russian")

    def normalize(token: str) -> str:
        return stemmer.stemWord(token.casefold())

    return normalize


def _document_in_scope(document: BenchmarkDocument, query: BenchmarkQuery) -> bool:
    if query.session_ids and document.session_id not in query.session_ids:
        return False
    document_date = date.fromisoformat(document.timestamp[:10])
    if query.date_from and document_date < date.fromisoformat(query.date_from):
        return False
    return not (query.date_to and document_date > date.fromisoformat(query.date_to))


def normalized_retrieval(
    normalizer: Normalizer,
    documents: tuple[BenchmarkDocument, ...] = BENCHMARK_DOCUMENTS,
) -> RetrievalFunction:
    """Build a morphology-aware retrieval function over the benchmark corpus."""

    index: list[tuple[int, BenchmarkDocument, list[str], Counter[str]]] = []
    for order_index, document in enumerate(documents):
        raw = _tokens(document.text)
        normalized = Counter(normalizer(token) for token in raw)
        index.append((order_index, document, raw, normalized))

    def _token_matches(
        raw_query: str,
        normalized_query: str,
        raw_tokens: list[str],
        lemmas: Counter[str],
    ) -> int:
        lemma_hits = lemmas.get(normalized_query, 0)
        prefix_hits = sum(1 for token in raw_tokens if token.startswith(raw_query))
        return lemma_hits + prefix_hits

    def retrieve(query: BenchmarkQuery) -> list[str]:
        raw_query_tokens = _tokens(query.text)
        if not raw_query_tokens:
            return []
        normalized_query_tokens = [normalizer(token) for token in raw_query_tokens]

        matches: list[tuple[int, int, str]] = []
        for order_index, document, raw_tokens, lemmas in index:
            if not _document_in_scope(document, query):
                continue
            per_token = [
                _token_matches(raw_query, normalized_query, raw_tokens, lemmas)
                for raw_query, normalized_query in zip(
                    raw_query_tokens, normalized_query_tokens, strict=True
                )
            ]
            if all(hits > 0 for hits in per_token):
                matches.append((-sum(per_token), order_index, document.doc_id))

        matches.sort()
        return [doc_id for _, _, doc_id in matches]

    return retrieve
