"""Hybrid history retrieval over source-grounded corpus references."""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.core.config import HistorySemanticSettings
from jarvis.journal.corpus import (
    HISTORY_SEARCH_MAX_RESULTS,
    HistoryCorpusEvent,
    HistoryCorpusRepository,
    HistoryEventRefsReadStatus,
    HistorySearchOrder,
    HistorySearchRequest,
    HistorySearchStatus,
)
from jarvis.journal.events import JournalEventRef
from jarvis.journal.semantic import (
    SEMANTIC_MAX_RESULTS,
    SemanticCandidateQuery,
    SemanticCandidateResult,
    SemanticCandidateStatus,
)

HISTORY_RETRIEVAL_MAX_RESULTS = HISTORY_SEARCH_MAX_RESULTS
_LEXICAL_FETCH_FACTOR = 3
_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)

TokenNormalizer = Callable[[str], str]


class SemanticCandidateStore(Protocol):
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult: ...


class HistoryRetrievalStatus(Enum):
    ACCEPTED = "accepted"
    INVALID_QUERY = "invalid_query"
    TOO_MANY_RESULTS = "too_many_results"
    LEXICAL_UNAVAILABLE = "lexical_unavailable"
    HYDRATION_FAILED = "hydration_failed"


class HistoryRetrievalSourceMode(Enum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    BOTH = "both"


@dataclass(frozen=True)
class HistoryRetrievalQuery:
    query: str
    limit: int = 20
    session_ids: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    roles: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoryRetrievalCandidate:
    reference: JournalEventRef
    text: str
    timestamp: str
    role: str
    source: str
    source_mode: HistoryRetrievalSourceMode
    combined_rank: int
    semantic_score: float | None = None
    lexical_score: float | None = None
    lexical_rank: int | None = None
    truncated: bool = False


@dataclass(frozen=True)
class HistoryRetrievalResult:
    status: HistoryRetrievalStatus
    candidates: tuple[HistoryRetrievalCandidate, ...] = ()
    lexical_count: int = 0
    semantic_count: int = 0
    returned_count: int = 0
    missing_references: tuple[JournalEventRef, ...] = ()
    max_results: int = HISTORY_RETRIEVAL_MAX_RESULTS


class Pymorphy3Normalizer:
    """Lazy pymorphy3 adapter for the selected local morphology backend."""

    def __init__(self) -> None:
        import pymorphy3

        self._analyzer = pymorphy3.MorphAnalyzer()
        self._cache: dict[str, str] = {}
        self._forms_cache: dict[str, tuple[str, ...]] = {}

    def normalize(self, token: str) -> str:
        folded = token.casefold()
        cached = self._cache.get(folded)
        if cached is None:
            cached = self._analyzer.parse(folded)[0].normal_form
            self._cache[folded] = cached
        return cached

    def forms(self, token: str) -> tuple[str, ...]:
        folded = token.casefold()
        cached = self._forms_cache.get(folded)
        if cached is not None:
            return cached
        parsed = self._analyzer.parse(folded)[0]
        forms = tuple(
            sorted({form.word.casefold() for form in parsed.lexeme} | {folded})
        )
        self._forms_cache[folded] = forms
        return forms


class HistoryRetrievalService:
    def __init__(
        self,
        repository: HistoryCorpusRepository,
        semantic_candidates: SemanticCandidateStore,
        semantic_settings: HistorySemanticSettings,
        normalizer: Pymorphy3Normalizer | None = None,
    ) -> None:
        self._repository = repository
        self._semantic_candidates = semantic_candidates
        self._semantic_settings = semantic_settings
        self._normalizer = normalizer

    def retrieve(self, request: HistoryRetrievalQuery) -> HistoryRetrievalResult:
        if not request.query.strip():
            return HistoryRetrievalResult(HistoryRetrievalStatus.INVALID_QUERY)
        if request.limit < 1 or request.limit > HISTORY_RETRIEVAL_MAX_RESULTS:
            return HistoryRetrievalResult(
                HistoryRetrievalStatus.TOO_MANY_RESULTS,
                max_results=HISTORY_RETRIEVAL_MAX_RESULTS,
            )

        lexical = self._lexical_candidates(request)
        if lexical is None:
            return HistoryRetrievalResult(HistoryRetrievalStatus.LEXICAL_UNAVAILABLE)
        semantic = self._semantic_candidates_for(request)
        fused = _fuse_candidates(lexical, semantic, request.limit)
        hydrated = self._repository.read_events(
            tuple(candidate.reference for candidate in fused)
        )
        if hydrated.status is not HistoryEventRefsReadStatus.ACCEPTED:
            return HistoryRetrievalResult(HistoryRetrievalStatus.HYDRATION_FAILED)

        events_by_reference = {event.reference: event for event in hydrated.events}
        candidates: list[HistoryRetrievalCandidate] = []
        for candidate in fused:
            event = events_by_reference.get(candidate.reference)
            if event is None:
                continue
            candidates.append(
                _to_retrieval_candidate(candidate, event, len(candidates) + 1)
            )

        return HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED,
            tuple(candidates),
            lexical_count=len(lexical),
            semantic_count=len(semantic),
            returned_count=len(candidates),
            missing_references=hydrated.missing_references,
        )

    def _lexical_candidates(
        self, request: HistoryRetrievalQuery
    ) -> tuple[_CandidateAccumulator, ...] | None:
        result = self._repository.search(
            HistorySearchRequest(
                query=request.query,
                term_groups=_term_groups(request.query, self._normalizer),
                date_from=request.date_from,
                date_to=request.date_to,
                session_ids=request.session_ids,
                roles=request.roles,
                sources=request.sources,
                limit=min(
                    request.limit * _LEXICAL_FETCH_FACTOR, HISTORY_SEARCH_MAX_RESULTS
                ),
                order=HistorySearchOrder.RELEVANCE,
            )
        )
        if result.status is HistorySearchStatus.UNAVAILABLE:
            return None
        if result.status is not HistorySearchStatus.ACCEPTED:
            return ()
        return tuple(
            _CandidateAccumulator(
                reference=hit.reference,
                lexical_score=hit.score,
                lexical_rank=hit.order_index + 1,
            )
            for hit in result.hits
        )

    def _semantic_candidates_for(
        self, request: HistoryRetrievalQuery
    ) -> tuple[_CandidateAccumulator, ...]:
        result = self._semantic_candidates.query(
            SemanticCandidateQuery(
                query=request.query,
                limit=min(request.limit * _LEXICAL_FETCH_FACTOR, SEMANTIC_MAX_RESULTS),
                session_ids=request.session_ids,
                date_from=request.date_from,
                date_to=request.date_to,
                roles=request.roles,
                sources=request.sources,
            )
        )
        if result.status is not SemanticCandidateStatus.ACCEPTED:
            return ()
        gated = _apply_relative_gate(
            result.candidates,
            separation=self._semantic_settings.separation,
            top_ratio=self._semantic_settings.top_ratio,
        )
        return tuple(
            _CandidateAccumulator(
                reference=candidate.reference,
                semantic_score=candidate.score,
            )
            for candidate in gated
        )


@dataclass(frozen=True)
class _CandidateAccumulator:
    reference: JournalEventRef
    semantic_score: float | None = None
    lexical_score: float | None = None
    lexical_rank: int | None = None


def _fuse_candidates(
    lexical: tuple[_CandidateAccumulator, ...],
    semantic: tuple[_CandidateAccumulator, ...],
    limit: int,
) -> tuple[_CandidateAccumulator, ...]:
    by_reference: dict[JournalEventRef, _CandidateAccumulator] = {}
    for candidate in lexical:
        by_reference[candidate.reference] = candidate
    for candidate in semantic:
        existing = by_reference.get(candidate.reference)
        if existing is None:
            by_reference[candidate.reference] = candidate
        else:
            by_reference[candidate.reference] = _CandidateAccumulator(
                reference=candidate.reference,
                semantic_score=candidate.semantic_score,
                lexical_score=existing.lexical_score,
                lexical_rank=existing.lexical_rank,
            )

    fused = sorted(
        by_reference.values(),
        key=lambda candidate: (
            0 if candidate.lexical_rank is not None else 1,
            candidate.lexical_rank or HISTORY_RETRIEVAL_MAX_RESULTS,
            -(candidate.semantic_score or -1.0),
            candidate.reference.session_id,
            candidate.reference.event_position,
        ),
    )
    return tuple(fused[:limit])


def _apply_relative_gate(
    candidates: tuple[object, ...],
    *,
    separation: float,
    top_ratio: float,
) -> tuple[object, ...]:
    if not candidates:
        return ()
    scores = [float(candidate.score) for candidate in candidates]
    top = max(scores)
    if top - statistics.median(scores) < separation:
        return ()
    cutoff = top * top_ratio
    return tuple(
        candidate for candidate in candidates if float(candidate.score) >= cutoff
    )


def _to_retrieval_candidate(
    candidate: _CandidateAccumulator,
    event: HistoryCorpusEvent,
    rank: int,
) -> HistoryRetrievalCandidate:
    if candidate.lexical_rank is not None and candidate.semantic_score is not None:
        source_mode = HistoryRetrievalSourceMode.BOTH
    elif candidate.semantic_score is not None:
        source_mode = HistoryRetrievalSourceMode.SEMANTIC
    else:
        source_mode = HistoryRetrievalSourceMode.LEXICAL
    return HistoryRetrievalCandidate(
        reference=candidate.reference,
        text=event.text,
        timestamp=event.timestamp,
        role=event.role,
        source=event.source,
        source_mode=source_mode,
        combined_rank=rank,
        semantic_score=candidate.semantic_score,
        lexical_score=candidate.lexical_score,
        lexical_rank=candidate.lexical_rank,
        truncated=False,
    )


def _term_groups(
    query: str, normalizer: Pymorphy3Normalizer | None
) -> tuple[tuple[str, ...], ...]:
    if normalizer is None:
        return ()
    return tuple(
        normalizer.forms(token) for token in _TOKEN_PATTERN.findall(query.casefold())
    )
