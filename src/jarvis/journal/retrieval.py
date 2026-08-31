"""Hybrid history retrieval over source-grounded corpus references.

The retrieval surface is single but its candidates are typed (task v1.8.0-23):
each result is either an event (a raw ``JournalEventRef`` hydrated from the
corpus) or an annotation (a derived note hydrated from the annotation overlay
store). Annotation text feeds the same ranked result, framed as derived data
with ``kind=annotation``, its source, and its target - it never enters the event
tables and is never surfaced as a raw user or assistant turn.
"""

from __future__ import annotations

import re
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.core.config import HistorySemanticSettings
from jarvis.journal.annotation import Annotation, AnnotationRead, AnnotationStatus
from jarvis.journal.annotation_search import (
    ANNOTATION_SEARCH_MAX_RESULTS,
    AnnotationSearchRequest,
    AnnotationSearchResult,
    AnnotationSearchStatus,
)
from jarvis.journal.annotation_semantic import (
    ANNOTATION_SEMANTIC_MAX_RESULTS,
    AnnotationSemanticQuery,
    AnnotationSemanticResult,
    AnnotationSemanticStatus,
)
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
from jarvis.journal.provenance import (
    ProvenanceDescriptor,
    provenance_descriptor_from_annotation_identity,
    provenance_descriptor_from_corpus_event,
)
from jarvis.journal.semantic import (
    SEMANTIC_MAX_RESULTS,
    SemanticCandidateQuery,
    SemanticCandidateResult,
    SemanticCandidateStatus,
)

HISTORY_RETRIEVAL_MAX_RESULTS = HISTORY_SEARCH_MAX_RESULTS
# Ranked candidates are hydrated in chunks this large so each ``read_events``
# batch stays within the repository's reference ceiling while the full fused
# list is still walked to fill ``limit`` past any stale rows.
_EVENT_HYDRATION_CHUNK = HISTORY_SEARCH_MAX_RESULTS
_LEXICAL_FETCH_FACTOR = 3
_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
_ANNOTATION_ROLE = "annotation"

TokenNormalizer = Callable[[str], str]


class SemanticCandidateStore(Protocol):
    def query(self, request: SemanticCandidateQuery) -> SemanticCandidateResult: ...


class AnnotationLexicalStore(Protocol):
    def search(self, request: AnnotationSearchRequest) -> AnnotationSearchResult: ...


class AnnotationSemanticStore(Protocol):
    def query(self, request: AnnotationSemanticQuery) -> AnnotationSemanticResult: ...


class AnnotationReadStore(Protocol):
    def read_annotation(self, annotation_id: str) -> AnnotationRead: ...


class HistoryRetrievalStatus(Enum):
    ACCEPTED = "accepted"
    INVALID_QUERY = "invalid_query"
    TOO_MANY_RESULTS = "too_many_results"
    LEXICAL_UNAVAILABLE = "lexical_unavailable"
    HYDRATION_FAILED = "hydration_failed"


class HistoryRetrievalFallbackMode(Enum):
    FULL_HYBRID = "full_hybrid"
    LEXICAL_BY_TIMEOUT = "lexical_by_timeout"
    LEXICAL_BY_UNAVAILABLE = "lexical_by_unavailable"


class HistoryRetrievalSourceMode(Enum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    BOTH = "both"


class HistoryRetrievalCandidateKind(Enum):
    """Whether a candidate is a raw source event or a derived annotation."""

    EVENT = "event"
    ANNOTATION = "annotation"


@dataclass(frozen=True)
class AnnotationCandidateIdentity:
    """The derived-note identity carried by an annotation candidate.

    ``source`` is the ``AnnotationSource`` value (``generated``/``edited``).
    ``start_position``/``end_position`` are both ``None`` for a whole-session
    annotation or both set for an inclusive event range - the same target
    contract the overlay store enforces.
    """

    annotation_id: str
    session_id: str
    source: str
    start_position: int | None = None
    end_position: int | None = None

    @property
    def is_whole_session(self) -> bool:
        return self.start_position is None and self.end_position is None


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
    """One ranked candidate.

    For an event candidate ``reference`` is set and ``annotation`` is ``None``;
    for an annotation candidate ``reference`` is ``None`` and ``annotation``
    carries the derived-note identity. ``kind`` discriminates the two so a
    consumer never mistakes derived annotation text for a raw turn.
    ``provenance`` is the task-1 descriptor computed at construction by the
    retrieval service from the candidate's event or annotation identity - the
    single authoritative "what kind of text is this" record. It is optional
    only for backward compatibility with candidates constructed outside the
    retrieval service (older tests, fixtures); the retrieval builders always
    set it. Raw-vs-transcript lives solely in ``provenance.source_kind``.
    """

    reference: JournalEventRef | None
    text: str
    timestamp: str
    role: str
    source: str
    source_mode: HistoryRetrievalSourceMode
    combined_rank: int
    kind: HistoryRetrievalCandidateKind = HistoryRetrievalCandidateKind.EVENT
    annotation: AnnotationCandidateIdentity | None = None
    provenance: ProvenanceDescriptor | None = None
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
    fallback_mode: HistoryRetrievalFallbackMode = (
        HistoryRetrievalFallbackMode.FULL_HYBRID
    )
    elapsed_seconds: float = 0.0
    missing_references: tuple[JournalEventRef, ...] = ()
    max_results: int = HISTORY_RETRIEVAL_MAX_RESULTS
    annotation_lexical_count: int = 0
    annotation_semantic_count: int = 0


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
        *,
        annotation_lexical: AnnotationLexicalStore | None = None,
        annotation_semantic: AnnotationSemanticStore | None = None,
        annotation_repository: AnnotationReadStore | None = None,
    ) -> None:
        self._repository = repository
        self._semantic_candidates = semantic_candidates
        self._semantic_settings = semantic_settings
        self._normalizer = normalizer
        self._annotation_lexical = annotation_lexical
        self._annotation_semantic = annotation_semantic
        self._annotation_repository = annotation_repository

    @property
    def _annotations_enabled(self) -> bool:
        return (
            self._annotation_lexical is not None
            or self._annotation_semantic is not None
        ) and self._annotation_repository is not None

    def retrieve(self, request: HistoryRetrievalQuery) -> HistoryRetrievalResult:
        started = time.perf_counter()
        if not request.query.strip():
            return HistoryRetrievalResult(
                HistoryRetrievalStatus.INVALID_QUERY,
                elapsed_seconds=time.perf_counter() - started,
            )
        if request.limit < 1 or request.limit > HISTORY_RETRIEVAL_MAX_RESULTS:
            return HistoryRetrievalResult(
                HistoryRetrievalStatus.TOO_MANY_RESULTS,
                max_results=HISTORY_RETRIEVAL_MAX_RESULTS,
                elapsed_seconds=time.perf_counter() - started,
            )

        lexical = self._lexical_candidates(request)
        if lexical is None:
            return HistoryRetrievalResult(
                HistoryRetrievalStatus.LEXICAL_UNAVAILABLE,
                elapsed_seconds=time.perf_counter() - started,
            )
        semantic, fallback_mode = self._semantic_candidates_for(request)
        annotation_lexical = self._annotation_lexical_candidates(request)
        annotation_semantic = self._annotation_semantic_candidates(request)
        fused = _fuse_candidates(
            (*lexical, *semantic, *annotation_lexical, *annotation_semantic)
        )

        collected = self._collect_candidates(fused, request.limit)
        if collected is None:
            return HistoryRetrievalResult(
                HistoryRetrievalStatus.HYDRATION_FAILED,
                elapsed_seconds=time.perf_counter() - started,
            )
        candidates, missing_references = collected

        return HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED,
            candidates,
            lexical_count=len(lexical),
            semantic_count=len(semantic),
            returned_count=len(candidates),
            fallback_mode=fallback_mode,
            elapsed_seconds=time.perf_counter() - started,
            missing_references=missing_references,
            annotation_lexical_count=len(annotation_lexical),
            annotation_semantic_count=len(annotation_semantic),
        )

    def _collect_candidates(
        self, fused: tuple[_CandidateAccumulator, ...], limit: int
    ) -> (
        tuple[tuple[HistoryRetrievalCandidate, ...], tuple[JournalEventRef, ...]] | None
    ):
        # Walk the fully ranked list, not a fixed top-``limit`` or top-500 prefix:
        # a candidate can drop on hydration (a missing event ref, or an annotation
        # deleted/dismissed since it was projected), and any prefix cut before
        # hydration would let a stale row consume a slot a valid lower-ranked
        # candidate should fill. Events are hydrated in ranked chunks bounded by
        # the ``read_events`` reference ceiling; annotations are read lazily, only
        # for the candidates actually reached before ``limit`` is met.
        candidates: list[HistoryRetrievalCandidate] = []
        missing: list[JournalEventRef] = []
        for start in range(0, len(fused), _EVENT_HYDRATION_CHUNK):
            if len(candidates) >= limit:
                break
            chunk = fused[start : start + _EVENT_HYDRATION_CHUNK]
            hydrated = self._hydrate_events(chunk)
            if hydrated is None:
                return None
            events_by_reference, chunk_missing = hydrated
            missing.extend(chunk_missing)
            for accumulator in chunk:
                if len(candidates) >= limit:
                    break
                candidate = self._build_candidate(
                    accumulator, events_by_reference, len(candidates) + 1
                )
                if candidate is not None:
                    candidates.append(candidate)
        return tuple(candidates), tuple(missing)

    def _hydrate_events(
        self, chunk: tuple[_CandidateAccumulator, ...]
    ) -> (
        tuple[dict[JournalEventRef, HistoryCorpusEvent], tuple[JournalEventRef, ...]]
        | None
    ):
        references = tuple(
            accumulator.reference
            for accumulator in chunk
            if accumulator.reference is not None
        )
        hydrated = self._repository.read_events(references)
        if hydrated.status is not HistoryEventRefsReadStatus.ACCEPTED:
            return None
        events_by_reference = {event.reference: event for event in hydrated.events}
        return events_by_reference, hydrated.missing_references

    def _build_candidate(
        self,
        accumulator: _CandidateAccumulator,
        events_by_reference: dict[JournalEventRef, HistoryCorpusEvent],
        rank: int,
    ) -> HistoryRetrievalCandidate | None:
        if accumulator.kind is HistoryRetrievalCandidateKind.EVENT:
            event = events_by_reference.get(accumulator.reference)  # type: ignore[arg-type]
            if event is None:
                return None
            return _event_candidate(accumulator, event, rank)
        return self._build_annotation_candidate(accumulator, rank)

    def _build_annotation_candidate(
        self, accumulator: _CandidateAccumulator, rank: int
    ) -> HistoryRetrievalCandidate | None:
        repository = self._annotation_repository
        if repository is None or accumulator.annotation_id is None:
            return None
        read = repository.read_annotation(accumulator.annotation_id)
        annotation = read.annotation if read.found else None
        if annotation is None or annotation.status is not AnnotationStatus.ACTIVE:
            return None
        return _annotation_candidate(accumulator, annotation, rank)

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
                kind=HistoryRetrievalCandidateKind.EVENT,
                reference=hit.reference,
                lexical_score=hit.score,
                lexical_rank=hit.order_index + 1,
            )
            for hit in result.hits
        )

    def _semantic_candidates_for(
        self, request: HistoryRetrievalQuery
    ) -> tuple[tuple[_CandidateAccumulator, ...], HistoryRetrievalFallbackMode]:
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
        if result.status is SemanticCandidateStatus.TIMEOUT:
            return (), HistoryRetrievalFallbackMode.LEXICAL_BY_TIMEOUT
        if result.status is SemanticCandidateStatus.UNAVAILABLE:
            return (), HistoryRetrievalFallbackMode.LEXICAL_BY_UNAVAILABLE
        if result.status is not SemanticCandidateStatus.ACCEPTED:
            return (), HistoryRetrievalFallbackMode.FULL_HYBRID
        gated = _apply_relative_gate(
            result.candidates,
            separation=self._semantic_settings.separation,
            top_ratio=self._semantic_settings.top_ratio,
        )
        return (
            tuple(
                _CandidateAccumulator(
                    kind=HistoryRetrievalCandidateKind.EVENT,
                    reference=candidate.reference,
                    semantic_score=candidate.score,
                )
                for candidate in gated
            ),
            HistoryRetrievalFallbackMode.FULL_HYBRID,
        )

    def _annotation_lexical_candidates(
        self, request: HistoryRetrievalQuery
    ) -> tuple[_CandidateAccumulator, ...]:
        store = self._annotation_lexical
        if store is None or self._annotation_repository is None:
            return ()
        # Annotation provenance ("generated"/"edited") and event roles/sources
        # are different vocabularies, so the event ``roles``/``sources`` filters
        # are deliberately not forwarded: annotations are eligible retrieval
        # candidates, not filtered by the event-centric surface.
        result = store.search(
            AnnotationSearchRequest(
                query=request.query,
                term_groups=_term_groups(request.query, self._normalizer),
                date_from=request.date_from,
                date_to=request.date_to,
                session_ids=request.session_ids,
                limit=min(
                    request.limit * _LEXICAL_FETCH_FACTOR, ANNOTATION_SEARCH_MAX_RESULTS
                ),
            )
        )
        if result.status is not AnnotationSearchStatus.ACCEPTED:
            return ()
        return tuple(
            _CandidateAccumulator(
                kind=HistoryRetrievalCandidateKind.ANNOTATION,
                annotation_id=hit.annotation_id,
                lexical_score=hit.score,
                lexical_rank=hit.order_index + 1,
            )
            for hit in result.hits
        )

    def _annotation_semantic_candidates(
        self, request: HistoryRetrievalQuery
    ) -> tuple[_CandidateAccumulator, ...]:
        store = self._annotation_semantic
        if store is None or self._annotation_repository is None:
            return ()
        result = store.query(
            AnnotationSemanticQuery(
                query=request.query,
                limit=min(
                    request.limit * _LEXICAL_FETCH_FACTOR,
                    ANNOTATION_SEMANTIC_MAX_RESULTS,
                ),
                session_ids=request.session_ids,
                date_from=request.date_from,
                date_to=request.date_to,
            )
        )
        if result.status is not AnnotationSemanticStatus.ACCEPTED:
            return ()
        gated = _apply_relative_gate(
            result.candidates,
            separation=self._semantic_settings.separation,
            top_ratio=self._semantic_settings.top_ratio,
        )
        return tuple(
            _CandidateAccumulator(
                kind=HistoryRetrievalCandidateKind.ANNOTATION,
                annotation_id=candidate.annotation_id,
                semantic_score=candidate.score,
            )
            for candidate in gated
        )


@dataclass(frozen=True)
class _CandidateAccumulator:
    kind: HistoryRetrievalCandidateKind
    reference: JournalEventRef | None = None
    annotation_id: str | None = None
    semantic_score: float | None = None
    lexical_score: float | None = None
    lexical_rank: int | None = None

    @property
    def fusion_key(self) -> tuple[str, str]:
        if self.kind is HistoryRetrievalCandidateKind.EVENT:
            assert self.reference is not None
            return (
                "event",
                f"{self.reference.session_id}\x00{self.reference.event_position}",
            )
        assert self.annotation_id is not None
        return ("annotation", self.annotation_id)

    @property
    def sort_identity(self) -> str:
        if self.kind is HistoryRetrievalCandidateKind.EVENT:
            assert self.reference is not None
            return (
                f"event\x00{self.reference.session_id}"
                f"\x00{self.reference.event_position:020d}"
            )
        assert self.annotation_id is not None
        return f"annotation\x00{self.annotation_id}"


def _fuse_candidates(
    candidates: tuple[_CandidateAccumulator, ...],
) -> tuple[_CandidateAccumulator, ...]:
    by_key: dict[tuple[str, str], _CandidateAccumulator] = {}
    for candidate in candidates:
        existing = by_key.get(candidate.fusion_key)
        if existing is None:
            by_key[candidate.fusion_key] = candidate
        else:
            by_key[candidate.fusion_key] = _merge_accumulators(existing, candidate)

    return tuple(
        sorted(
            by_key.values(),
            key=lambda candidate: (
                0 if candidate.lexical_rank is not None else 1,
                candidate.lexical_rank or HISTORY_RETRIEVAL_MAX_RESULTS,
                -(candidate.semantic_score or -1.0),
                candidate.sort_identity,
            ),
        )
    )


def _merge_accumulators(
    first: _CandidateAccumulator, second: _CandidateAccumulator
) -> _CandidateAccumulator:
    return _CandidateAccumulator(
        kind=first.kind,
        reference=first.reference or second.reference,
        annotation_id=first.annotation_id or second.annotation_id,
        semantic_score=(
            first.semantic_score
            if first.semantic_score is not None
            else second.semantic_score
        ),
        lexical_score=(
            first.lexical_score
            if first.lexical_score is not None
            else second.lexical_score
        ),
        lexical_rank=(
            first.lexical_rank
            if first.lexical_rank is not None
            else second.lexical_rank
        ),
    )


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


def _event_candidate(
    accumulator: _CandidateAccumulator,
    event: HistoryCorpusEvent,
    rank: int,
) -> HistoryRetrievalCandidate:
    return HistoryRetrievalCandidate(
        reference=accumulator.reference,
        text=event.indexed_text,
        timestamp=event.timestamp,
        role=event.role,
        source=event.source,
        source_mode=_source_mode(accumulator),
        combined_rank=rank,
        kind=HistoryRetrievalCandidateKind.EVENT,
        provenance=provenance_descriptor_from_corpus_event(event),
        semantic_score=accumulator.semantic_score,
        lexical_score=accumulator.lexical_score,
        lexical_rank=accumulator.lexical_rank,
        truncated=False,
    )


def _annotation_candidate(
    accumulator: _CandidateAccumulator,
    annotation: Annotation,
    rank: int,
) -> HistoryRetrievalCandidate:
    identity = AnnotationCandidateIdentity(
        annotation_id=annotation.annotation_id,
        session_id=annotation.target.session_id,
        source=annotation.source.value,
        start_position=annotation.target.start_position,
        end_position=annotation.target.end_position,
    )
    return HistoryRetrievalCandidate(
        reference=None,
        text=annotation.text,
        timestamp=annotation.created_at,
        role=_ANNOTATION_ROLE,
        source=annotation.source.value,
        source_mode=_source_mode(accumulator),
        combined_rank=rank,
        kind=HistoryRetrievalCandidateKind.ANNOTATION,
        annotation=identity,
        provenance=provenance_descriptor_from_annotation_identity(identity),
        semantic_score=accumulator.semantic_score,
        lexical_score=accumulator.lexical_score,
        lexical_rank=accumulator.lexical_rank,
        truncated=False,
    )


def _source_mode(accumulator: _CandidateAccumulator) -> HistoryRetrievalSourceMode:
    if accumulator.lexical_rank is not None and accumulator.semantic_score is not None:
        return HistoryRetrievalSourceMode.BOTH
    if accumulator.semantic_score is not None:
        return HistoryRetrievalSourceMode.SEMANTIC
    return HistoryRetrievalSourceMode.LEXICAL


def _term_groups(
    query: str, normalizer: Pymorphy3Normalizer | None
) -> tuple[tuple[str, ...], ...]:
    if normalizer is None:
        return ()
    return tuple(
        normalizer.forms(token) for token in _TOKEN_PATTERN.findall(query.casefold())
    )
