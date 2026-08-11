from dataclasses import dataclass

from jarvis.core.bus import EventBus
from jarvis.core.config import HISTORY_TOOL_PROVIDER_NAME, DataBoundary, McpSettings
from jarvis.core.solo_session import SoloSessionState
from jarvis.journal import (
    AnnotationCandidateIdentity,
    HistoryBatchRead,
    HistoryBatchReadStatus,
    HistoryCorpusEvent,
    HistoryEventRange,
    HistoryEventRangeRead,
    HistoryEventRangeStatus,
    HistoryEventRefsRead,
    HistoryEventRefsReadStatus,
    HistoryRetrievalCandidate,
    HistoryRetrievalCandidateKind,
    HistoryRetrievalQuery,
    HistoryRetrievalResult,
    HistoryRetrievalSourceMode,
    HistoryRetrievalStatus,
    JournalEventRef,
)
from jarvis.tools.history import (
    READ_HISTORY_RANGES_TOOL_NAME,
    READ_HISTORY_TOOL_NAME,
    SEARCH_HISTORY_TOOL_NAME,
    HistoryToolProvider,
)
from jarvis.tools.host import McpHost, McpModuleStatus
from jarvis.tools.registry import ToolRegistry


def _event(
    session_id: str,
    event_position: int,
    *,
    text: str,
    role: str = "user",
    source: str = "text",
) -> HistoryCorpusEvent:
    return HistoryCorpusEvent(
        reference=JournalEventRef(session_id, event_position),
        timestamp="2026-08-01T10:00:00Z",
        timestamp_sort=1.0 + event_position,
        role=role,
        source=source,
        text=text,
        media=(),
        media_count=0,
        transcript=None,
        metadata={},
    )


@dataclass
class FakeRetrievalService:
    result: HistoryRetrievalResult

    def __post_init__(self) -> None:
        self.calls: list[HistoryRetrievalQuery] = []

    def retrieve(self, request: HistoryRetrievalQuery) -> HistoryRetrievalResult:
        self.calls.append(request)
        return self.result


@dataclass
class FakeRepository:
    read_events_result: HistoryEventRefsRead
    read_surrounding_result: HistoryEventRangeRead
    read_ranges_result: HistoryBatchRead

    def __post_init__(self) -> None:
        self.read_events_calls: list[tuple[JournalEventRef, ...]] = []
        self.read_surrounding_calls: list[tuple[JournalEventRef, int, int]] = []
        self.read_ranges_calls: list[tuple[HistoryEventRange, ...]] = []

    def read_events(
        self, references: tuple[JournalEventRef, ...]
    ) -> HistoryEventRefsRead:
        self.read_events_calls.append(references)
        return self.read_events_result

    def read_surrounding(
        self, reference: JournalEventRef, *, before: int, after: int
    ) -> HistoryEventRangeRead:
        self.read_surrounding_calls.append((reference, before, after))
        return self.read_surrounding_result

    def read_ranges(self, ranges: tuple[HistoryEventRange, ...]) -> HistoryBatchRead:
        self.read_ranges_calls.append(ranges)
        return self.read_ranges_result


def _provider(
    *,
    retrieval_result: HistoryRetrievalResult | None = None,
    read_events_result: HistoryEventRefsRead | None = None,
    read_surrounding_result: HistoryEventRangeRead | None = None,
    read_ranges_result: HistoryBatchRead | None = None,
    solo_session_state: SoloSessionState | None = None,
    current_session_id: str | None = None,
) -> tuple[FakeRepository, FakeRetrievalService, HistoryToolProvider]:
    repository = FakeRepository(
        read_events_result=read_events_result
        or HistoryEventRefsRead(HistoryEventRefsReadStatus.ACCEPTED),
        read_surrounding_result=read_surrounding_result
        or HistoryEventRangeRead(HistoryEventRangeStatus.FOUND),
        read_ranges_result=read_ranges_result
        or HistoryBatchRead(HistoryBatchReadStatus.ACCEPTED),
    )
    retrieval = FakeRetrievalService(
        retrieval_result or HistoryRetrievalResult(HistoryRetrievalStatus.ACCEPTED)
    )
    provider = HistoryToolProvider(
        repository=repository,  # type: ignore[arg-type]
        retrieval_service=retrieval,  # type: ignore[arg-type]
        solo_session_state=solo_session_state,
        current_session_id=lambda: current_session_id,
    )
    return repository, retrieval, provider


def test_history_provider_registers_reserved_local_tools() -> None:
    _, _, provider = _provider()
    registry = ToolRegistry()

    provider.register_tools(registry)

    tools = {tool.name: tool for tool in registry.all()}
    assert set(tools) == {
        SEARCH_HISTORY_TOOL_NAME,
        READ_HISTORY_TOOL_NAME,
        READ_HISTORY_RANGES_TOOL_NAME,
    }
    assert all(tool.provider == HISTORY_TOOL_PROVIDER_NAME for tool in tools.values())
    assert all(tool.provider_kind == "builtin" for tool in tools.values())
    assert all(tool.data_boundary is DataBoundary.LOCAL for tool in tools.values())


async def test_search_history_rejects_token_budget_before_retrieval() -> None:
    _, retrieval, provider = _provider()

    result = await provider.call_tool(
        SEARCH_HISTORY_TOOL_NAME,
        {"query": "project relay", "limit": 2, "max_tokens": 600},
    )

    assert result.is_error is True
    assert "max_tokens is too small" in str(result.content)
    assert retrieval.calls == []


async def test_search_history_returns_grounded_provenance_and_filters() -> None:
    candidate = HistoryRetrievalCandidate(
        reference=JournalEventRef("20260801-100000-ab12", 3),
        text="A" * 260,
        timestamp="2026-08-01T10:00:00Z",
        role="assistant",
        source="text",
        source_mode=HistoryRetrievalSourceMode.BOTH,
        combined_rank=1,
        semantic_score=0.91,
        lexical_score=-0.2,
        lexical_rank=1,
    )
    _, retrieval, provider = _provider(
        retrieval_result=HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED,
            candidates=(candidate,),
            lexical_count=1,
            semantic_count=1,
            returned_count=1,
        )
    )

    result = await provider.call_tool(
        SEARCH_HISTORY_TOOL_NAME,
        {
            "query": "relay status",
            "limit": 1,
            "session_ids": ["20260801-100000-ab12"],
            "roles": ["assistant"],
            "sources": ["text"],
            "date_from": "2026-08-01",
        },
    )

    assert result.is_error is False
    assert len(retrieval.calls) == 1
    assert retrieval.calls[0] == HistoryRetrievalQuery(
        query="relay status",
        limit=1,
        session_ids=("20260801-100000-ab12",),
        date_from="2026-08-01",
        roles=("assistant",),
        sources=("text",),
    )
    assert result.structured_content["truncated_count"] == 1
    [item] = result.structured_content["results"]
    assert item["kind"] == "event"
    assert item["reference"] == {
        "session_id": "20260801-100000-ab12",
        "event_position": 3,
    }
    assert item["source_mode"] == "both"
    assert item["truncated"] is True
    assert str(item["text"]).endswith("...")


async def test_search_history_reports_solo_restricted_false_by_default() -> None:
    _, _, provider = _provider(
        retrieval_result=HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED, returned_count=0
        )
    )

    result = await provider.call_tool(SEARCH_HISTORY_TOOL_NAME, {"query": "relay"})

    assert result.structured_content["solo_restricted"] is False


async def test_search_history_forces_session_ids_to_current_session_while_solo() -> (
    None
):
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    _, retrieval, provider = _provider(
        retrieval_result=HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED, returned_count=0
        ),
        solo_session_state=solo,
        current_session_id="20260801-100000-ab12",
    )

    result = await provider.call_tool(
        SEARCH_HISTORY_TOOL_NAME,
        {"query": "relay", "session_ids": ["20260731-090000-zz99"]},
    )

    assert result.is_error is False
    [query] = retrieval.calls
    assert query.session_ids == ("20260801-100000-ab12",)
    assert result.structured_content["solo_restricted"] is True


async def test_search_history_rejects_while_solo_active_with_no_current_session() -> (
    None
):
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    _, retrieval, provider = _provider(solo_session_state=solo, current_session_id=None)

    result = await provider.call_tool(SEARCH_HISTORY_TOOL_NAME, {"query": "relay"})

    assert result.is_error is True
    assert retrieval.calls == []


async def test_search_history_is_unrestricted_when_solo_is_off() -> None:
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=False)
    _, retrieval, provider = _provider(
        retrieval_result=HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED, returned_count=0
        ),
        solo_session_state=solo,
        current_session_id="20260801-100000-ab12",
    )

    result = await provider.call_tool(SEARCH_HISTORY_TOOL_NAME, {"query": "relay"})

    [query] = retrieval.calls
    assert query.session_ids == ()
    assert result.structured_content["solo_restricted"] is False


async def test_read_history_rejects_reference_outside_current_session_while_solo() -> (
    None
):
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    repository, _, provider = _provider(
        solo_session_state=solo, current_session_id="20260801-100000-ab12"
    )

    result = await provider.call_tool(
        READ_HISTORY_TOOL_NAME,
        {"references": [{"session_id": "20260731-090000-zz99", "event_position": 0}]},
    )

    assert result.is_error is True
    assert "Solo mode" in str(result.content)
    assert "20260731-090000-zz99" in str(result.content)
    assert repository.read_events_calls == []


async def test_read_history_allows_reference_inside_current_session_while_solo() -> (
    None
):
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    repository, _, provider = _provider(
        solo_session_state=solo, current_session_id="20260801-100000-ab12"
    )

    result = await provider.call_tool(
        READ_HISTORY_TOOL_NAME,
        {"references": [{"session_id": "20260801-100000-ab12", "event_position": 0}]},
    )

    assert result.is_error is False
    assert repository.read_events_calls == [
        (JournalEventRef("20260801-100000-ab12", 0),)
    ]


async def test_read_history_anchor_outside_current_session_rejected_while_solo() -> (
    None
):
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    repository, _, provider = _provider(
        solo_session_state=solo, current_session_id="20260801-100000-ab12"
    )

    result = await provider.call_tool(
        READ_HISTORY_TOOL_NAME,
        {"anchor": {"session_id": "20260731-090000-zz99", "event_position": 0}},
    )

    assert result.is_error is True
    assert repository.read_surrounding_calls == []


async def test_read_history_ranges_rejects_range_outside_session_while_solo() -> None:
    bus = EventBus()
    solo = SoloSessionState(bus, enabled=True)
    repository, _, provider = _provider(
        solo_session_state=solo, current_session_id="20260801-100000-ab12"
    )

    result = await provider.call_tool(
        READ_HISTORY_RANGES_TOOL_NAME,
        {
            "ranges": [
                {
                    "start": {
                        "session_id": "20260731-090000-zz99",
                        "event_position": 0,
                    },
                    "end": {
                        "session_id": "20260731-090000-zz99",
                        "event_position": 1,
                    },
                }
            ]
        },
    )

    assert result.is_error is True
    assert repository.read_ranges_calls == []


async def test_search_history_frames_annotation_as_typed_derived_candidate() -> None:
    candidate = HistoryRetrievalCandidate(
        reference=None,
        text="Пользователь предпочитает краткие ответы.",
        timestamp="2026-08-01T10:00:00Z",
        role="annotation",
        source="generated",
        source_mode=HistoryRetrievalSourceMode.SEMANTIC,
        combined_rank=1,
        kind=HistoryRetrievalCandidateKind.ANNOTATION,
        annotation=AnnotationCandidateIdentity(
            annotation_id="ann-1",
            session_id="20260801-100000-ab12",
            source="generated",
            start_position=2,
            end_position=5,
        ),
        semantic_score=0.88,
    )
    _, _, provider = _provider(
        retrieval_result=HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED,
            candidates=(candidate,),
            annotation_semantic_count=1,
            returned_count=1,
        )
    )

    result = await provider.call_tool(
        SEARCH_HISTORY_TOOL_NAME,
        {"query": "краткие ответы", "limit": 1},
    )

    assert result.is_error is False
    [item] = result.structured_content["results"]
    assert item["kind"] == "annotation"
    assert item["annotation_id"] == "ann-1"
    assert item["target"] == {
        "session_id": "20260801-100000-ab12",
        "start_position": 2,
        "end_position": 5,
    }
    assert item["source"] == "generated"
    assert "reference" not in item
    assert "text_is_transcript" not in item
    assert item["source_mode"] == "semantic"


async def test_read_history_reports_missing_reference_as_a_tool_error() -> None:
    first = JournalEventRef("20260801-100000-ab12", 0)
    missing = JournalEventRef("20260801-100000-ab12", 9)
    repository, _, provider = _provider(
        read_events_result=HistoryEventRefsRead(
            HistoryEventRefsReadStatus.ACCEPTED,
            events=(
                _event(first.session_id, first.event_position, text="First event"),
            ),
            missing_references=(missing,),
        )
    )

    result = await provider.call_tool(
        READ_HISTORY_TOOL_NAME,
        {
            "references": [
                {
                    "session_id": first.session_id,
                    "event_position": first.event_position,
                },
                {
                    "session_id": missing.session_id,
                    "event_position": missing.event_position,
                },
            ]
        },
    )

    assert result.is_error is True
    assert repository.read_events_calls == [(first, missing)]
    assert result.structured_content["missing_references"] == [
        {"session_id": "20260801-100000-ab12", "event_position": 9}
    ]
    assert result.structured_content["returned_count"] == 1


async def test_read_history_surrounding_rejects_over_limit_before_repository_work() -> (
    None
):
    repository, _, provider = _provider()

    result = await provider.call_tool(
        READ_HISTORY_TOOL_NAME,
        {
            "anchor": {"session_id": "20260801-100000-ab12", "event_position": 3},
            "before": 3,
            "after": 3,
        },
    )

    assert result.is_error is True
    assert "at most 6 total events" in str(result.content)
    assert repository.read_surrounding_calls == []


async def test_read_history_ranges_surfaces_per_range_failures() -> None:
    good_range = HistoryEventRange(
        JournalEventRef("20260801-100000-ab12", 0),
        JournalEventRef("20260801-100000-ab12", 1),
    )
    bad_range = HistoryEventRange(
        JournalEventRef("20260801-100000-ab12", 2),
        JournalEventRef("20260801-100000-ab12", 9),
    )
    repository, _, provider = _provider(
        read_ranges_result=HistoryBatchRead(
            HistoryBatchReadStatus.ACCEPTED,
            ranges=(
                HistoryEventRangeRead(
                    HistoryEventRangeStatus.FOUND,
                    requested_range=good_range,
                    events=(
                        _event("20260801-100000-ab12", 0, text="Zero"),
                        _event("20260801-100000-ab12", 1, text="One"),
                    ),
                    requested_count=2,
                ),
                HistoryEventRangeRead(
                    HistoryEventRangeStatus.UNKNOWN_END_REFERENCE,
                    requested_range=bad_range,
                    missing_reference=JournalEventRef("20260801-100000-ab12", 9),
                    requested_count=8,
                ),
            ),
            total_events=2,
            requested_events=4,
        )
    )

    result = await provider.call_tool(
        READ_HISTORY_RANGES_TOOL_NAME,
        {
            "ranges": [
                {
                    "start": {
                        "session_id": "20260801-100000-ab12",
                        "event_position": 0,
                    },
                    "end": {"session_id": "20260801-100000-ab12", "event_position": 1},
                },
                {
                    "start": {
                        "session_id": "20260801-100000-ab12",
                        "event_position": 2,
                    },
                    "end": {"session_id": "20260801-100000-ab12", "event_position": 5},
                },
            ]
        },
    )

    assert result.is_error is True
    assert repository.read_ranges_calls == [
        (
            good_range,
            HistoryEventRange(
                JournalEventRef("20260801-100000-ab12", 2),
                JournalEventRef("20260801-100000-ab12", 5),
            ),
        )
    ]
    assert [entry["status"] for entry in result.structured_content["ranges"]] == [
        "found",
        "unknown_end_reference",
    ]


async def test_history_tools_dispatch_while_mcp_is_off() -> None:
    first = JournalEventRef("20260801-100000-ab12", 0)
    repository, retrieval, provider = _provider(
        retrieval_result=HistoryRetrievalResult(
            HistoryRetrievalStatus.ACCEPTED,
            candidates=(
                HistoryRetrievalCandidate(
                    reference=first,
                    text="Relay status stored.",
                    timestamp="2026-08-01T10:00:00Z",
                    role="assistant",
                    source="text",
                    source_mode=HistoryRetrievalSourceMode.LEXICAL,
                    combined_rank=1,
                    lexical_score=-0.1,
                    lexical_rank=1,
                ),
            ),
            lexical_count=1,
            semantic_count=0,
            returned_count=1,
        )
    )
    registry = ToolRegistry()
    provider.register_tools(registry)
    host = McpHost(
        EventBus(),
        McpSettings(),
        registry=registry,
        builtin_clients={HISTORY_TOOL_PROVIDER_NAME: provider},
    )

    result = await host.dispatcher.dispatch(
        SEARCH_HISTORY_TOOL_NAME, {"query": "relay status", "limit": 1}
    )

    assert host.status is McpModuleStatus.OFF
    assert result.ok is True
    assert repository.read_events_calls == []
    assert len(retrieval.calls) == 1
