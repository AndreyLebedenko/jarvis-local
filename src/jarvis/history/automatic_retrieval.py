"""Pure automatic-retrieval selection over hybrid history candidates."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.history.context_budget import PromptTokenEstimator
from jarvis.history.recent_history import RecentHistorySelection
from jarvis.history.working_context import (
    RetrievedHistoryPassage,
    estimate_working_context_tokens,
    format_retrieved_history_passages,
)
from jarvis.journal import HistoryRetrievalCandidate, HistoryRetrievalQuery

__all__ = [
    "AutomaticRetrievalRequest",
    "AutomaticRetrievalSelection",
    "AutomaticRetrievalSelectionLimits",
    "build_automatic_retrieval_request",
    "select_automatic_retrieval_passages",
    "to_history_retrieval_query",
]

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
_DEFAULT_ROLES = ("user", "assistant")
_DEFAULT_SOURCES = ("text",)
_RECENT_RETRIEVAL_ROLES = {"user", "assistant"}


@dataclass(frozen=True)
class AutomaticRetrievalRequest:
    current_user_text: str
    recent_history: RecentHistorySelection
    query_text: str
    session_ids: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    roles: tuple[str, ...] = _DEFAULT_ROLES
    sources: tuple[str, ...] = _DEFAULT_SOURCES


@dataclass(frozen=True)
class AutomaticRetrievalSelectionLimits:
    candidate_limit: int = 8
    passage_limit: int = 3
    minimum_relevance: float = 0.5
    token_budget: int = 2048

    def __post_init__(self) -> None:
        _require_positive("candidate_limit", self.candidate_limit)
        _require_positive("passage_limit", self.passage_limit)
        _require_positive("token_budget", self.token_budget)
        if not 0.0 <= self.minimum_relevance <= 1.0:
            raise ValueError(
                "minimum_relevance must be between 0.0 and 1.0, "
                f"got {self.minimum_relevance!r}"
            )


@dataclass(frozen=True)
class AutomaticRetrievalSelection:
    request: AutomaticRetrievalRequest
    selected_passages: tuple[RetrievedHistoryPassage, ...]
    inspected_candidate_count: int
    skipped_empty_count: int
    skipped_duplicate_count: int
    skipped_weak_count: int
    skipped_capacity_count: int
    estimated_tokens: int
    token_budget: int

    @property
    def selected_passage_count(self) -> int:
        return len(self.selected_passages)


def build_automatic_retrieval_request(
    current_user_text: str,
    recent_history: RecentHistorySelection,
    *,
    session_ids: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
    roles: tuple[str, ...] = _DEFAULT_ROLES,
    sources: tuple[str, ...] = _DEFAULT_SOURCES,
) -> AutomaticRetrievalRequest:
    query_text = _compose_query_text(current_user_text, recent_history)
    return AutomaticRetrievalRequest(
        current_user_text=current_user_text,
        recent_history=recent_history,
        query_text=query_text,
        session_ids=session_ids,
        date_from=date_from,
        date_to=date_to,
        roles=roles,
        sources=sources,
    )


def to_history_retrieval_query(
    request: AutomaticRetrievalRequest,
    *,
    limit: int,
) -> HistoryRetrievalQuery:
    return HistoryRetrievalQuery(
        query=request.query_text,
        limit=limit,
        session_ids=request.session_ids,
        date_from=request.date_from,
        date_to=request.date_to,
        roles=request.roles,
        sources=request.sources,
    )


def select_automatic_retrieval_passages(
    request: AutomaticRetrievalRequest,
    candidates: Sequence[HistoryRetrievalCandidate],
    limits: AutomaticRetrievalSelectionLimits,
    *,
    estimator: PromptTokenEstimator,
) -> AutomaticRetrievalSelection:
    if not request.query_text.strip():
        return AutomaticRetrievalSelection(
            request=request,
            selected_passages=(),
            inspected_candidate_count=0,
            skipped_empty_count=0,
            skipped_duplicate_count=0,
            skipped_weak_count=0,
            skipped_capacity_count=0,
            estimated_tokens=0,
            token_budget=limits.token_budget,
        )

    recent_texts = tuple(
        turn.text
        for turn in request.recent_history.turns
        if turn.role in _RECENT_RETRIEVAL_ROLES
    )
    current_text_norm = _normalize_text(request.current_user_text)
    selected: list[RetrievedHistoryPassage] = []
    skipped_empty = 0
    skipped_duplicate = 0
    skipped_weak = 0
    skipped_capacity = 0

    for candidate in tuple(candidates[: limits.candidate_limit]):
        normalized_candidate_text = _normalize_text(candidate.text)
        if not normalized_candidate_text:
            skipped_empty += 1
            continue
        if current_text_norm and normalized_candidate_text == current_text_norm:
            skipped_duplicate += 1
            continue
        if _is_recent_overlap(candidate.text, recent_texts):
            skipped_duplicate += 1
            continue
        if _candidate_relevance(candidate) < limits.minimum_relevance:
            skipped_weak += 1
            continue

        passage = _to_retrieved_history_passage(candidate)
        tentative = (*selected, passage)
        if len(tentative) > limits.passage_limit:
            skipped_capacity += 1
            continue
        if _estimate_passage_tokens(tentative, estimator) > limits.token_budget:
            skipped_capacity += 1
            continue
        selected.append(passage)

    selected_passages = tuple(selected)
    estimated_tokens = _estimate_passage_tokens(selected_passages, estimator)
    return AutomaticRetrievalSelection(
        request=request,
        selected_passages=selected_passages,
        inspected_candidate_count=min(len(candidates), limits.candidate_limit),
        skipped_empty_count=skipped_empty,
        skipped_duplicate_count=skipped_duplicate,
        skipped_weak_count=skipped_weak,
        skipped_capacity_count=skipped_capacity,
        estimated_tokens=estimated_tokens,
        token_budget=limits.token_budget,
    )


def _compose_query_text(
    current_user_text: str,
    recent_history: RecentHistorySelection,
) -> str:
    parts: list[str] = []
    current = current_user_text.strip()
    if current:
        parts.append(current)
    for turn in recent_history.turns:
        if turn.role not in _RECENT_RETRIEVAL_ROLES:
            continue
        text = turn.text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _candidate_relevance(candidate: HistoryRetrievalCandidate) -> float:
    scores: list[float] = []
    if candidate.semantic_score is not None:
        scores.append(candidate.semantic_score)
    if candidate.lexical_rank is not None and candidate.lexical_rank > 0:
        scores.append(1.0 / candidate.lexical_rank)
    return max(scores) if scores else 0.0


def _is_recent_overlap(candidate_text: str, recent_texts: Sequence[str]) -> bool:
    candidate_tokens = _tokenize_text(candidate_text)
    if not candidate_tokens:
        return False
    for recent_text in recent_texts:
        recent_tokens = _tokenize_text(recent_text)
        if not recent_tokens:
            continue
        if candidate_tokens == recent_tokens:
            return True
        if _contains_token_sequence(recent_tokens, candidate_tokens):
            return True
    return False


def _to_retrieved_history_passage(
    candidate: HistoryRetrievalCandidate,
) -> RetrievedHistoryPassage:
    return RetrievedHistoryPassage(
        reference=candidate.reference,
        role=candidate.role,
        source=candidate.source,
        timestamp=candidate.timestamp,
        text=candidate.text,
        truncated=False,
    )


def _estimate_passage_tokens(
    passages: tuple[RetrievedHistoryPassage, ...] | list[RetrievedHistoryPassage],
    estimator: PromptTokenEstimator,
) -> int:
    if not passages:
        return 0
    message = {
        "role": "system",
        "content": format_retrieved_history_passages(passages),
    }
    return estimate_working_context_tokens((message,), estimator=estimator)


def _normalize_text(text: str) -> str:
    return " ".join(_tokenize_text(text))


def _tokenize_text(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(text.casefold()))


def _contains_token_sequence(
    haystack: tuple[str, ...],
    needle: tuple[str, ...],
) -> bool:
    if len(needle) > len(haystack):
        return False
    needle_length = len(needle)
    for start in range(len(haystack) - needle_length + 1):
        if haystack[start : start + needle_length] == needle:
            return True
    return False


def _require_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")
