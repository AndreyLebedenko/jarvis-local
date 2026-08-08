"""Read-only local history tools over the typed history domain APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from jarvis.core.config import HISTORY_TOOL_PROVIDER_NAME, DataBoundary
from jarvis.journal import (
    AnnotationCandidateIdentity,
    HistoryBatchRead,
    HistoryBatchReadStatus,
    HistoryCorpusEvent,
    HistoryCorpusRepository,
    HistoryEventRange,
    HistoryEventRangeRead,
    HistoryEventRangeStatus,
    HistoryEventRefsRead,
    HistoryEventRefsReadStatus,
    HistoryRetrievalCandidate,
    HistoryRetrievalCandidateKind,
    HistoryRetrievalQuery,
    HistoryRetrievalResult,
    HistoryRetrievalService,
    HistoryRetrievalStatus,
    JournalEventRef,
)
from jarvis.journal.events import parse_journal_timestamp
from jarvis.tools.json_types import JSONObject
from jarvis.tools.registry import RegisteredTool, ToolRegistry
from jarvis.tools.results import ToolArguments, ToolCallResult

SEARCH_HISTORY_TOOL_NAME = "search_history"
READ_HISTORY_TOOL_NAME = "read_history"
READ_HISTORY_RANGES_TOOL_NAME = "read_history_ranges"

_VALID_ROLES = {"user", "assistant", "system"}
_ESTIMATED_BASE_RESULT_TOKENS = 200
_ESTIMATED_TOKENS_PER_EVENT = 240
_DEFAULT_MAX_RESULT_TOKENS = 1800
_MAX_RESULT_TOKENS = 2048
_MIN_RESULT_TOKENS = _ESTIMATED_BASE_RESULT_TOKENS + _ESTIMATED_TOKENS_PER_EVENT
_DEFAULT_SEARCH_LIMIT = 5
_MAX_SEARCH_LIMIT = 6
_MAX_READ_REFERENCES = 6
_MAX_SURROUNDING_EVENTS = 6
_MAX_RANGE_BATCHES = 3
_MAX_RANGE_TOTAL_EVENTS = 6
_EVENT_TEXT_CHAR_LIMIT = 200


class HistoryToolProvider:
    def __init__(
        self,
        *,
        repository: HistoryCorpusRepository,
        retrieval_service: HistoryRetrievalService,
    ) -> None:
        self._repository = repository
        self._retrieval_service = retrieval_service

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.set_provider_tools(HISTORY_TOOL_PROVIDER_NAME, _history_tools())

    async def call_tool(self, name: str, arguments: ToolArguments) -> ToolCallResult:
        if name == SEARCH_HISTORY_TOOL_NAME:
            return self._search_history(arguments)
        if name == READ_HISTORY_TOOL_NAME:
            return self._read_history(arguments)
        if name == READ_HISTORY_RANGES_TOOL_NAME:
            return self._read_history_ranges(arguments)
        return ToolCallResult(content=f"Unknown history tool: {name}", is_error=True)

    def _search_history(self, arguments: ToolArguments) -> ToolCallResult:
        parsed = _parse_search_call(arguments)
        if isinstance(parsed, ToolCallResult):
            return parsed
        result = self._retrieval_service.retrieve(
            HistoryRetrievalQuery(
                query=parsed.query,
                limit=parsed.limit,
                session_ids=parsed.session_ids,
                date_from=parsed.date_from,
                date_to=parsed.date_to,
                roles=parsed.roles,
                sources=parsed.sources,
            )
        )
        status_error = _retrieval_status_error(result)
        if status_error is not None:
            return status_error
        items, truncated_count = _serialize_retrieval_candidates(result.candidates)
        payload: JSONObject = {
            "summary": (
                f"Found {result.returned_count} grounded history matches for "
                f"{parsed.query!r}; "
                f"lexical candidates={result.lexical_count}, "
                f"semantic candidates={result.semantic_count}."
            ),
            "query": parsed.query,
            "returned_count": result.returned_count,
            "requested_limit": parsed.limit,
            "max_tokens": parsed.max_tokens,
            "lexical_count": result.lexical_count,
            "semantic_count": result.semantic_count,
            "missing_references": [
                _reference_payload(reference) for reference in result.missing_references
            ],
            "truncated_count": truncated_count,
            "results": items,
        }
        return ToolCallResult(
            content=str(payload["summary"]),
            structured_content=payload,
        )

    def _read_history(self, arguments: ToolArguments) -> ToolCallResult:
        parsed = _parse_read_call(arguments)
        if isinstance(parsed, ToolCallResult):
            return parsed
        if isinstance(parsed, _ReferenceReadCall):
            result = self._repository.read_events(parsed.references)
            return _event_refs_result(result, max_tokens=parsed.max_tokens)
        result = self._repository.read_surrounding(
            parsed.anchor, before=parsed.before, after=parsed.after
        )
        return _range_read_result(
            result,
            max_tokens=parsed.max_tokens,
            summary_prefix=(
                f"Read {parsed.before + parsed.after + 1} event slots around "
                f"{parsed.anchor.session_id}:{parsed.anchor.event_position}"
            ),
        )

    def _read_history_ranges(self, arguments: ToolArguments) -> ToolCallResult:
        parsed = _parse_ranges_call(arguments)
        if isinstance(parsed, ToolCallResult):
            return parsed
        result = self._repository.read_ranges(parsed.ranges)
        return _batch_read_result(result, max_tokens=parsed.max_tokens)


def _history_tools() -> list[RegisteredTool]:
    return [
        RegisteredTool(
            name=SEARCH_HISTORY_TOOL_NAME,
            description=(
                "Search local conversation history with hybrid lexical and semantic "
                "retrieval. Returns grounded text passages with provenance."
            ),
            schema=_search_history_schema(),
            provider=HISTORY_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=READ_HISTORY_TOOL_NAME,
            description=(
                "Read grounded local history either by explicit references or as "
                "bounded surrounding context around one anchor event."
            ),
            schema=_read_history_schema(),
            provider=HISTORY_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=READ_HISTORY_RANGES_TOOL_NAME,
            description=(
                "Read and compare several bounded local history ranges in one call."
            ),
            schema=_read_history_ranges_schema(),
            provider=HISTORY_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
    ]


def _search_history_schema() -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_SEARCH_LIMIT,
                "default": _DEFAULT_SEARCH_LIMIT,
            },
            "max_tokens": {
                "type": "integer",
                "minimum": _MIN_RESULT_TOKENS,
                "maximum": _MAX_RESULT_TOKENS,
                "default": _DEFAULT_MAX_RESULT_TOKENS,
            },
            "session_ids": {"type": "array", "items": {"type": "string"}},
            "date_from": {"type": "string"},
            "date_to": {"type": "string"},
            "roles": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(_VALID_ROLES)},
            },
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def _reference_schema() -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "minLength": 1},
            "event_position": {"type": "integer", "minimum": 0},
        },
        "required": ["session_id", "event_position"],
        "additionalProperties": False,
    }


def _range_schema() -> JSONObject:
    reference = _reference_schema()
    return {
        "type": "object",
        "properties": {
            "start": reference,
            "end": reference,
        },
        "required": ["start", "end"],
        "additionalProperties": False,
    }


def _read_history_schema() -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "references": {
                "type": "array",
                "items": _reference_schema(),
                "minItems": 1,
                "maxItems": _MAX_READ_REFERENCES,
            },
            "anchor": _reference_schema(),
            "before": {
                "type": "integer",
                "minimum": 0,
                "maximum": _MAX_SURROUNDING_EVENTS - 1,
                "default": 0,
            },
            "after": {
                "type": "integer",
                "minimum": 0,
                "maximum": _MAX_SURROUNDING_EVENTS - 1,
                "default": 0,
            },
            "max_tokens": {
                "type": "integer",
                "minimum": _MIN_RESULT_TOKENS,
                "maximum": _MAX_RESULT_TOKENS,
                "default": _DEFAULT_MAX_RESULT_TOKENS,
            },
        },
        "additionalProperties": False,
        "anyOf": [
            {"required": ["references"]},
            {"required": ["anchor"]},
        ],
    }


def _read_history_ranges_schema() -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "ranges": {
                "type": "array",
                "items": _range_schema(),
                "minItems": 1,
                "maxItems": _MAX_RANGE_BATCHES,
            },
            "max_tokens": {
                "type": "integer",
                "minimum": _MIN_RESULT_TOKENS,
                "maximum": _MAX_RESULT_TOKENS,
                "default": _DEFAULT_MAX_RESULT_TOKENS,
            },
        },
        "required": ["ranges"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class _SerializedEvent:
    payload: JSONObject
    truncated: bool


@dataclass(frozen=True)
class _SearchCall:
    query: str
    limit: int
    max_tokens: int
    session_ids: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    roles: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class _ReferenceReadCall:
    references: tuple[JournalEventRef, ...]
    max_tokens: int


@dataclass(frozen=True)
class _AnchorReadCall:
    anchor: JournalEventRef
    before: int
    after: int
    max_tokens: int


@dataclass(frozen=True)
class _RangesReadCall:
    ranges: tuple[HistoryEventRange, ...]
    max_tokens: int


@dataclass(frozen=True)
class _SearchFilters:
    session_ids: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    roles: tuple[str, ...]
    sources: tuple[str, ...]


def _parse_search_call(arguments: ToolArguments) -> _SearchCall | ToolCallResult:
    unknown = set(arguments) - {
        "query",
        "limit",
        "max_tokens",
        "session_ids",
        "date_from",
        "date_to",
        "roles",
        "sources",
    }
    if unknown:
        return _argument_error(SEARCH_HISTORY_TOOL_NAME, unknown)
    raw_query = arguments.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        return ToolCallResult(
            content="query must be a non-empty string",
            is_error=True,
        )
    limit = _parse_positive_int(
        arguments.get("limit", _DEFAULT_SEARCH_LIMIT),
        name="limit",
        maximum=_MAX_SEARCH_LIMIT,
    )
    if isinstance(limit, ToolCallResult):
        return limit
    max_tokens = _parse_max_tokens(
        arguments.get("max_tokens", _DEFAULT_MAX_RESULT_TOKENS)
    )
    if isinstance(max_tokens, ToolCallResult):
        return max_tokens
    filters = _parse_search_filters(arguments)
    if isinstance(filters, ToolCallResult):
        return filters
    budget_error = _validate_output_budget(max_tokens=max_tokens, event_count=limit)
    if budget_error is not None:
        return budget_error
    return _SearchCall(
        query=raw_query.strip(),
        limit=limit,
        max_tokens=max_tokens,
        session_ids=filters.session_ids,
        date_from=filters.date_from,
        date_to=filters.date_to,
        roles=filters.roles,
        sources=filters.sources,
    )


def _parse_search_filters(arguments: ToolArguments) -> _SearchFilters | ToolCallResult:
    session_ids = _parse_string_list(
        arguments.get("session_ids", ()),
        name="session_ids",
    )
    if isinstance(session_ids, ToolCallResult):
        return session_ids
    roles = _parse_roles(arguments.get("roles", ()))
    if isinstance(roles, ToolCallResult):
        return roles
    sources = _parse_string_list(arguments.get("sources", ()), name="sources")
    if isinstance(sources, ToolCallResult):
        return sources
    date_from = _parse_optional_date_like(arguments.get("date_from"), "date_from")
    if isinstance(date_from, ToolCallResult):
        return date_from
    date_to = _parse_optional_date_like(arguments.get("date_to"), "date_to")
    if isinstance(date_to, ToolCallResult):
        return date_to
    return _SearchFilters(
        session_ids=session_ids,
        date_from=date_from,
        date_to=date_to,
        roles=roles,
        sources=sources,
    )


def _parse_read_call(
    arguments: ToolArguments,
) -> _ReferenceReadCall | _AnchorReadCall | ToolCallResult:
    unknown = set(arguments) - {"references", "anchor", "before", "after", "max_tokens"}
    if unknown:
        return _argument_error(READ_HISTORY_TOOL_NAME, unknown)
    has_references = "references" in arguments
    has_anchor = "anchor" in arguments
    if has_references == has_anchor:
        return ToolCallResult(
            content=(
                "Provide exactly one read mode: either references=[...] "
                "or anchor={...} with optional before/after"
            ),
            is_error=True,
        )
    if has_references:
        return _parse_reference_read_call(arguments)
    return _parse_anchor_read_call(arguments)


def _parse_reference_read_call(
    arguments: ToolArguments,
) -> _ReferenceReadCall | ToolCallResult:
    if "before" in arguments or "after" in arguments:
        return ToolCallResult(
            content="before/after may be used only with anchor reads",
            is_error=True,
        )
    max_tokens = _parse_max_tokens(
        arguments.get("max_tokens", _DEFAULT_MAX_RESULT_TOKENS)
    )
    if isinstance(max_tokens, ToolCallResult):
        return max_tokens
    references = _parse_reference_list(
        arguments.get("references"),
        name="references",
        maximum=_MAX_READ_REFERENCES,
    )
    if isinstance(references, ToolCallResult):
        return references
    budget_error = _validate_output_budget(
        max_tokens=max_tokens,
        event_count=len(references),
    )
    if budget_error is not None:
        return budget_error
    return _ReferenceReadCall(references=references, max_tokens=max_tokens)


def _parse_anchor_read_call(
    arguments: ToolArguments,
) -> _AnchorReadCall | ToolCallResult:
    max_tokens = _parse_max_tokens(
        arguments.get("max_tokens", _DEFAULT_MAX_RESULT_TOKENS)
    )
    if isinstance(max_tokens, ToolCallResult):
        return max_tokens
    anchor = _parse_reference(arguments.get("anchor"), name="anchor")
    if isinstance(anchor, ToolCallResult):
        return anchor
    before = _parse_positive_int(arguments.get("before", 0), name="before", minimum=0)
    if isinstance(before, ToolCallResult):
        return before
    after = _parse_positive_int(arguments.get("after", 0), name="after", minimum=0)
    if isinstance(after, ToolCallResult):
        return after
    requested_events = before + after + 1
    if requested_events > _MAX_SURROUNDING_EVENTS:
        return ToolCallResult(
            content=(
                "anchor reads may request at most "
                f"{_MAX_SURROUNDING_EVENTS} total events, got {requested_events}"
            ),
            is_error=True,
        )
    budget_error = _validate_output_budget(
        max_tokens=max_tokens,
        event_count=requested_events,
    )
    if budget_error is not None:
        return budget_error
    return _AnchorReadCall(
        anchor=anchor,
        before=before,
        after=after,
        max_tokens=max_tokens,
    )


def _parse_ranges_call(arguments: ToolArguments) -> _RangesReadCall | ToolCallResult:
    unknown = set(arguments) - {"ranges", "max_tokens"}
    if unknown:
        return _argument_error(READ_HISTORY_RANGES_TOOL_NAME, unknown)
    ranges = _parse_range_list(
        arguments.get("ranges"),
        name="ranges",
        maximum=_MAX_RANGE_BATCHES,
    )
    if isinstance(ranges, ToolCallResult):
        return ranges
    total_requested_events = sum(event_range.requested_count for event_range in ranges)
    if total_requested_events > _MAX_RANGE_TOTAL_EVENTS:
        return ToolCallResult(
            content=(
                "read_history_ranges may request at most "
                f"{_MAX_RANGE_TOTAL_EVENTS} total events, got {total_requested_events}"
            ),
            is_error=True,
        )
    max_tokens = _parse_max_tokens(
        arguments.get("max_tokens", _DEFAULT_MAX_RESULT_TOKENS)
    )
    if isinstance(max_tokens, ToolCallResult):
        return max_tokens
    budget_error = _validate_output_budget(
        max_tokens=max_tokens,
        event_count=total_requested_events,
    )
    if budget_error is not None:
        return budget_error
    return _RangesReadCall(ranges=ranges, max_tokens=max_tokens)


def _parse_max_tokens(value: object) -> int | ToolCallResult:
    return _parse_positive_int(
        value,
        name="max_tokens",
        minimum=_MIN_RESULT_TOKENS,
        maximum=_MAX_RESULT_TOKENS,
    )


def _parse_roles(value: object) -> tuple[str, ...] | ToolCallResult:
    roles = _parse_string_list(value, name="roles")
    if isinstance(roles, ToolCallResult):
        return roles
    invalid_roles = [role for role in roles if role not in _VALID_ROLES]
    if invalid_roles:
        return ToolCallResult(
            content=(
                "roles may contain only: "
                f"{', '.join(sorted(_VALID_ROLES))}; got {', '.join(invalid_roles)}"
            ),
            is_error=True,
        )
    return roles


def _retrieval_status_error(
    result: HistoryRetrievalResult,
) -> ToolCallResult | None:
    if result.status is HistoryRetrievalStatus.ACCEPTED:
        return None
    if result.status is HistoryRetrievalStatus.INVALID_QUERY:
        return ToolCallResult(
            content="query must be a non-empty string",
            is_error=True,
        )
    if result.status is HistoryRetrievalStatus.TOO_MANY_RESULTS:
        return ToolCallResult(
            content=(
                f"limit exceeds the maximum of {result.max_results} retrieval results"
            ),
            is_error=True,
        )
    if result.status is HistoryRetrievalStatus.LEXICAL_UNAVAILABLE:
        return ToolCallResult(
            content=(
                "History search is unavailable because the lexical "
                "projection is missing"
            ),
            is_error=True,
        )
    return ToolCallResult(
        content="History search failed to hydrate source-grounded events",
        is_error=True,
    )


def _event_refs_result(
    result: HistoryEventRefsRead,
    *,
    max_tokens: int,
) -> ToolCallResult:
    if result.status is HistoryEventRefsReadStatus.TOO_MANY_REFERENCES:
        return ToolCallResult(
            content=(
                "read_history references exceed the domain maximum of "
                f"{result.max_references}"
            ),
            is_error=True,
        )
    events, truncated_count = _serialize_events(result.events)
    payload: JSONObject = {
        "summary": (
            f"Read {len(result.events)} history event(s); "
            f"missing references={len(result.missing_references)}."
        ),
        "returned_count": len(result.events),
        "missing_references": [
            _reference_payload(reference) for reference in result.missing_references
        ],
        "truncated_count": truncated_count,
        "max_tokens": max_tokens,
        "events": events,
    }
    if result.missing_references:
        return ToolCallResult(
            content=(
                "One or more requested history references were not found; "
                "see structured_content.missing_references."
            ),
            is_error=True,
            structured_content=payload,
        )
    return ToolCallResult(
        content=str(payload["summary"]),
        structured_content=payload,
    )


def _range_read_result(
    result: HistoryEventRangeRead,
    *,
    max_tokens: int,
    summary_prefix: str,
) -> ToolCallResult:
    if result.status is not HistoryEventRangeStatus.FOUND:
        payload: JSONObject = {
            "summary": f"{summary_prefix} failed with status {result.status.value}.",
            "status": result.status.value,
            "requested_count": result.requested_count,
            "max_events": result.max_events,
            "missing_reference": (
                None
                if result.missing_reference is None
                else _reference_payload(result.missing_reference)
            ),
            "requested_range": (
                None
                if result.requested_range is None
                else _range_payload(result.requested_range)
            ),
            "max_tokens": max_tokens,
        }
        return ToolCallResult(
            content=str(payload["summary"]),
            is_error=True,
            structured_content=payload,
        )
    events, truncated_count = _serialize_events(result.events)
    payload = {
        "summary": f"{summary_prefix}; returned {len(result.events)} event(s).",
        "status": result.status.value,
        "requested_count": result.requested_count,
        "returned_count": len(result.events),
        "max_events": result.max_events,
        "truncated_count": truncated_count,
        "requested_range": (
            None
            if result.requested_range is None
            else _range_payload(result.requested_range)
        ),
        "max_tokens": max_tokens,
        "events": events,
    }
    return ToolCallResult(
        content=str(payload["summary"]),
        structured_content=payload,
    )


def _batch_read_result(
    result: HistoryBatchRead,
    *,
    max_tokens: int,
) -> ToolCallResult:
    if result.status is HistoryBatchReadStatus.TOO_MANY_RANGES:
        return ToolCallResult(
            content=f"Too many ranges requested; maximum is {result.max_ranges}",
            is_error=True,
        )
    if result.status is HistoryBatchReadStatus.TOO_MANY_EVENTS:
        return ToolCallResult(
            content=(
                "Requested range batch exceeds the event cap: "
                f"{result.requested_events} > {result.max_events}"
            ),
            is_error=True,
        )
    payload_ranges: list[JSONObject] = []
    truncated_count = 0
    all_found = True
    for range_read in result.ranges:
        events, range_truncated = _serialize_events(range_read.events)
        truncated_count += range_truncated
        payload_ranges.append(
            {
                "status": range_read.status.value,
                "requested_range": (
                    None
                    if range_read.requested_range is None
                    else _range_payload(range_read.requested_range)
                ),
                "requested_count": range_read.requested_count,
                "returned_count": len(range_read.events),
                "missing_reference": (
                    None
                    if range_read.missing_reference is None
                    else _reference_payload(range_read.missing_reference)
                ),
                "events": events,
            }
        )
        all_found = all_found and range_read.status is HistoryEventRangeStatus.FOUND
    payload: JSONObject = {
        "summary": (
            f"Read {len(result.ranges)} history range(s); returned "
            f"{result.total_events} event(s) from {result.requested_events} requested."
        ),
        "status": result.status.value,
        "range_count": len(result.ranges),
        "returned_count": result.total_events,
        "requested_count": result.requested_events,
        "truncated_count": truncated_count,
        "max_ranges": result.max_ranges,
        "max_events": result.max_events,
        "max_tokens": max_tokens,
        "ranges": payload_ranges,
    }
    if not all_found:
        return ToolCallResult(
            content=(
                "One or more requested history ranges were invalid or missing; "
                "see structured_content.ranges."
            ),
            is_error=True,
            structured_content=payload,
        )
    return ToolCallResult(
        content=str(payload["summary"]),
        structured_content=payload,
    )


def _serialize_retrieval_candidates(
    candidates: tuple[HistoryRetrievalCandidate, ...],
) -> tuple[list[JSONObject], int]:
    serialized: list[JSONObject] = []
    truncated_count = 0
    for candidate in candidates:
        text = _truncate_text(candidate.text)
        truncated = text.truncated or candidate.truncated
        truncated_count += int(truncated)
        payload: JSONObject = {
            "kind": candidate.kind.value,
            "timestamp": candidate.timestamp,
            "source": candidate.source,
            "text": text.payload["text"],
            "truncated": truncated,
            "source_mode": candidate.source_mode.value,
            "combined_rank": candidate.combined_rank,
            "semantic_score": candidate.semantic_score,
            "lexical_score": candidate.lexical_score,
            "lexical_rank": candidate.lexical_rank,
        }
        if (
            candidate.kind is HistoryRetrievalCandidateKind.ANNOTATION
            and candidate.annotation is not None
        ):
            payload["annotation_id"] = candidate.annotation.annotation_id
            payload["target"] = _annotation_target_payload(candidate.annotation)
        else:
            payload["reference"] = _reference_payload(candidate.reference)
            payload["role"] = candidate.role
            payload["text_is_transcript"] = candidate.text_is_transcript
        serialized.append(payload)
    return serialized, truncated_count


def _annotation_target_payload(annotation: AnnotationCandidateIdentity) -> JSONObject:
    return {
        "session_id": annotation.session_id,
        "start_position": annotation.start_position,
        "end_position": annotation.end_position,
    }


def _serialize_events(
    events: tuple[HistoryCorpusEvent, ...],
) -> tuple[list[JSONObject], int]:
    serialized: list[JSONObject] = []
    truncated_count = 0
    for event in events:
        text = _truncate_text(event.indexed_text)
        truncated_count += int(text.truncated)
        serialized.append(
            {
                "reference": _reference_payload(event.reference),
                "timestamp": event.timestamp,
                "role": event.role,
                "source": event.source,
                "text": text.payload["text"],
                "truncated": text.truncated,
                "text_is_transcript": event.text_is_transcript,
                "media_count": event.media_count,
                "transcript": event.transcript,
            }
        )
    return serialized, truncated_count


def _truncate_text(text: str) -> _SerializedEvent:
    if len(text) <= _EVENT_TEXT_CHAR_LIMIT:
        return _SerializedEvent({"text": text}, truncated=False)
    truncated = text[: _EVENT_TEXT_CHAR_LIMIT - 3].rstrip() + "..."
    return _SerializedEvent({"text": truncated}, truncated=True)


def _reference_payload(reference: JournalEventRef) -> JSONObject:
    return {
        "session_id": reference.session_id,
        "event_position": reference.event_position,
    }


def _range_payload(event_range: HistoryEventRange) -> JSONObject:
    return {
        "start": _reference_payload(event_range.start),
        "end": _reference_payload(event_range.end),
    }


def _parse_reference_list(
    value: object, *, name: str, maximum: int
) -> tuple[JournalEventRef, ...] | ToolCallResult:
    if not isinstance(value, list) or not value:
        return ToolCallResult(
            content=f"{name} must be a non-empty array of references",
            is_error=True,
        )
    if len(value) > maximum:
        return ToolCallResult(
            content=f"{name} may contain at most {maximum} references",
            is_error=True,
        )
    references: list[JournalEventRef] = []
    for index, item in enumerate(value):
        reference = _parse_reference(item, name=f"{name}[{index}]")
        if isinstance(reference, ToolCallResult):
            return reference
        references.append(reference)
    return tuple(references)


def _parse_range_list(
    value: object, *, name: str, maximum: int
) -> tuple[HistoryEventRange, ...] | ToolCallResult:
    if not isinstance(value, list) or not value:
        return ToolCallResult(
            content=f"{name} must be a non-empty array of ranges",
            is_error=True,
        )
    if len(value) > maximum:
        return ToolCallResult(
            content=f"{name} may contain at most {maximum} ranges",
            is_error=True,
        )
    ranges: list[HistoryEventRange] = []
    for index, item in enumerate(value):
        event_range = _parse_range(item, name=f"{name}[{index}]")
        if isinstance(event_range, ToolCallResult):
            return event_range
        ranges.append(event_range)
    return tuple(ranges)


def _parse_range(value: object, *, name: str) -> HistoryEventRange | ToolCallResult:
    if not isinstance(value, dict):
        return ToolCallResult(content=f"{name} must be an object", is_error=True)
    unknown = set(value) - {"start", "end"}
    if unknown:
        names = ", ".join(sorted(str(item) for item in unknown))
        return ToolCallResult(
            content=f"{name} received unsupported key(s): {names}",
            is_error=True,
        )
    start = _parse_reference(value.get("start"), name=f"{name}.start")
    if isinstance(start, ToolCallResult):
        return start
    end = _parse_reference(value.get("end"), name=f"{name}.end")
    if isinstance(end, ToolCallResult):
        return end
    if start.session_id != end.session_id:
        return ToolCallResult(
            content=f"{name} must stay within one session",
            is_error=True,
        )
    if end.event_position < start.event_position:
        return ToolCallResult(
            content=f"{name} end.event_position must be >= start.event_position",
            is_error=True,
        )
    return HistoryEventRange(start, end)


def _parse_reference(value: object, *, name: str) -> JournalEventRef | ToolCallResult:
    if not isinstance(value, dict):
        return ToolCallResult(content=f"{name} must be an object", is_error=True)
    unknown = set(value) - {"session_id", "event_position"}
    if unknown:
        names = ", ".join(sorted(str(item) for item in unknown))
        return ToolCallResult(
            content=f"{name} received unsupported key(s): {names}",
            is_error=True,
        )
    session_id = value.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return ToolCallResult(
            content=f"{name}.session_id must be a non-empty string",
            is_error=True,
        )
    event_position = value.get("event_position")
    if not isinstance(event_position, int) or isinstance(event_position, bool):
        return ToolCallResult(
            content=f"{name}.event_position must be an integer",
            is_error=True,
        )
    if event_position < 0:
        return ToolCallResult(
            content=f"{name}.event_position must be >= 0",
            is_error=True,
        )
    return JournalEventRef(session_id.strip(), event_position)


def _parse_optional_date_like(value: object, name: str) -> str | None | ToolCallResult:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return ToolCallResult(
            content=f"{name} must be an ISO date or full journal timestamp string",
            is_error=True,
        )
    text = value.strip()
    try:
        date.fromisoformat(text)
        return text
    except ValueError:
        try:
            parse_journal_timestamp(text)
        except ValueError:
            return ToolCallResult(
                content=f"{name} must be an ISO date or full journal timestamp string",
                is_error=True,
            )
        return text


def _parse_string_list(value: object, *, name: str) -> tuple[str, ...] | ToolCallResult:
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        return ToolCallResult(
            content=f"{name} must be an array of non-empty strings",
            is_error=True,
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return ToolCallResult(
                content=f"{name} must be an array of non-empty strings",
                is_error=True,
            )
        items.append(item.strip())
    return tuple(items)


def _parse_positive_int(
    value: object,
    *,
    name: str,
    minimum: int = 1,
    maximum: int | None = None,
) -> int | ToolCallResult:
    if not isinstance(value, int) or isinstance(value, bool):
        return ToolCallResult(
            content=f"{name} must be an integer",
            is_error=True,
        )
    if value < minimum:
        return ToolCallResult(
            content=f"{name} must be >= {minimum}",
            is_error=True,
        )
    if maximum is not None and value > maximum:
        return ToolCallResult(
            content=f"{name} must be <= {maximum}",
            is_error=True,
        )
    return value


def _validate_output_budget(
    *, max_tokens: int, event_count: int
) -> ToolCallResult | None:
    estimated = (
        _ESTIMATED_BASE_RESULT_TOKENS + _ESTIMATED_TOKENS_PER_EVENT * event_count
    )
    if estimated > max_tokens:
        return ToolCallResult(
            content=(
                "Requested max_tokens is too small for this history read: "
                f"estimated {estimated} tokens for {event_count} event(s), "
                f"got {max_tokens}. Reduce the requested count or raise max_tokens "
                f"up to {_MAX_RESULT_TOKENS}."
            ),
            is_error=True,
            structured_content={
                "estimated_tokens": estimated,
                "requested_max_tokens": max_tokens,
                "event_count": event_count,
            },
        )
    return None


def _argument_error(tool_name: str, unknown: set[str]) -> ToolCallResult:
    names = ", ".join(sorted(unknown))
    return ToolCallResult(
        content=f"{tool_name} received unsupported argument(s): {names}",
        is_error=True,
    )
