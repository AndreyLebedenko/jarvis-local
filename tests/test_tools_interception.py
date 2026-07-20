import asyncio
import contextlib

from jarvis.core.bus import EventBus
from jarvis.core.config import DataBoundary
from jarvis.tools.interception import (
    ToolCallFinished,
    ToolCallStarted,
    ToolDispatcher,
    summarize_outbound,
)
from jarvis.tools.mcp_client import McpTransportError, ToolCallResult
from jarvis.tools.registry import RegisteredTool, ToolRegistry
from jarvis.ui.contract import SystemEvent


class FakeClient:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self._result = result or ToolCallResult(content="ok")
        self._exc = exc

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self._exc is not None:
            raise self._exc
        return self._result


class _Admission:
    """Test double for McpHost's admission gate - defaults to always
    admitting, matching an "enabled" module."""

    def __init__(self, admitting: bool = True):
        self.admitting = admitting
        self.inflight = 0
        self.enter_calls = 0
        self.exit_calls = 0

    def enter(self, provider: str) -> bool:
        del provider
        self.enter_calls += 1
        if not self.admitting:
            return False
        self.inflight += 1
        return True

    def exit(self, provider: str) -> None:
        del provider
        self.exit_calls += 1
        self.inflight -= 1


def _dispatcher(
    bus, registry, clients: dict, admission: _Admission | None = None, **kwargs
) -> ToolDispatcher:
    admission = admission or _Admission()
    return ToolDispatcher(
        bus, registry, clients.get, admission.enter, admission.exit, **kwargs
    )


def _registry_with(tool: RegisteredTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_provider_tools(tool.provider, [tool])
    return registry


def _enabled_tool(
    name: str = "web_search",
    enabled: bool = True,
    data_boundary: DataBoundary = DataBoundary.UNKNOWN,
) -> RegisteredTool:
    return RegisteredTool(
        name=name,
        description="",
        schema={},
        provider="search",
        enabled=enabled,
        data_boundary=data_boundary,
    )


async def test_dispatch_events_carry_the_registered_tool_data_boundary():
    bus = EventBus()
    started = await _collect(bus, ToolCallStarted)
    finished = await _collect(bus, ToolCallFinished)
    tool = _enabled_tool(data_boundary=DataBoundary.INTERNET)
    dispatcher = _dispatcher(bus, _registry_with(tool), {"search": FakeClient()})

    await dispatcher.dispatch("web_search", {"query": "weather"})

    assert started[0].data_boundary is DataBoundary.INTERNET
    assert finished[0].data_boundary is DataBoundary.INTERNET


async def test_dispatch_maps_canonical_call_to_upstream_name_and_fixed_arguments():
    bus = EventBus()
    started = await _collect(bus, ToolCallStarted)
    tool = RegisteredTool(
        name="web_search",
        description="",
        schema={},
        provider="search",
        upstream_name="search_text",
        allowed_arguments=("query",),
        fixed_arguments={"backend": "duckduckgo", "max_results": 5},
    )
    client = FakeClient()
    dispatcher = _dispatcher(bus, _registry_with(tool), {"search": client})

    result = await dispatcher.dispatch("web_search", {"query": "local AI news"})

    assert result.ok is True
    assert client.calls == [
        (
            "search_text",
            {
                "query": "local AI news",
                "backend": "duckduckgo",
                "max_results": 5,
            },
        )
    ]
    assert started[0].tool_name == "web_search"
    assert started[0].arguments == {
        "query": "local AI news",
        "backend": "duckduckgo",
        "max_results": 5,
    }
    assert "backend='duckduckgo'" in started[0].outbound_summary


async def test_dispatch_rejects_arguments_hidden_by_the_canonical_adapter():
    bus = EventBus()
    started = await _collect(bus, ToolCallStarted)
    tool = RegisteredTool(
        name="web_search",
        description="",
        schema={},
        provider="search",
        upstream_name="search_text",
        allowed_arguments=("query",),
        fixed_arguments={"backend": "duckduckgo"},
    )
    client = FakeClient()
    dispatcher = _dispatcher(bus, _registry_with(tool), {"search": client})

    result = await dispatcher.dispatch(
        "web_search", {"query": "weather", "backend": "bing"}
    )

    assert result.ok is False
    assert "unsupported argument" in result.error
    assert client.calls == []
    assert started == []


async def test_rejected_registered_tool_keeps_its_data_boundary_in_outcome():
    bus = EventBus()
    finished = await _collect(bus, ToolCallFinished)
    tool = _enabled_tool(enabled=False, data_boundary=DataBoundary.LAN)
    dispatcher = _dispatcher(bus, _registry_with(tool), {})

    await dispatcher.dispatch("web_search", {})

    assert finished[0].data_boundary is DataBoundary.LAN


async def _collect(bus: EventBus, event_type) -> list:
    events: list = []

    async def handler(event):
        events.append(event)

    bus.subscribe(event_type, handler)
    return events


async def test_dispatch_returns_disabled_error_when_module_is_off():
    registry = _registry_with(_enabled_tool())
    dispatcher = _dispatcher(EventBus(), registry, {}, _Admission(admitting=False))

    result = await dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert result.error == "Provider not available: 'search'"
    assert result.correlation_id


async def test_dispatch_when_not_admitted_never_calls_exit():
    """enter_dispatch() returning False means dispatch() never actually
    entered - exit_dispatch() must not be called for a slot that was
    never granted."""
    admission = _Admission(admitting=False)
    dispatcher = _dispatcher(EventBus(), _registry_with(_enabled_tool()), {}, admission)

    await dispatcher.dispatch("web_search", {})

    assert admission.enter_calls == 1
    assert admission.exit_calls == 0


async def test_dispatch_always_releases_the_admitted_slot():
    registry = _registry_with(_enabled_tool())
    client = FakeClient()
    admission = _Admission()
    dispatcher = _dispatcher(EventBus(), registry, {"search": client}, admission)

    await dispatcher.dispatch("web_search", {})

    assert admission.inflight == 0
    assert admission.exit_calls == 1


async def test_dispatch_unknown_tool_is_an_error_without_calling_any_client():
    client = FakeClient()
    dispatcher = _dispatcher(EventBus(), ToolRegistry(), {"search": client})

    result = await dispatcher.dispatch("nope", {})

    assert result.ok is False
    assert "Unknown tool" in result.error
    assert client.calls == []


async def test_dispatch_disabled_tool_is_an_error_without_calling_any_client():
    registry = _registry_with(_enabled_tool(enabled=False))
    client = FakeClient()
    dispatcher = _dispatcher(EventBus(), registry, {"search": client})

    result = await dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert "Tool disabled" in result.error
    assert client.calls == []


async def test_dispatch_missing_provider_client_is_an_error():
    registry = _registry_with(_enabled_tool())
    dispatcher = _dispatcher(EventBus(), registry, {})

    result = await dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert "not connected" in result.error


async def test_dispatch_calls_the_owning_provider_client_with_the_given_arguments():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(result=ToolCallResult(content="4 results"))
    dispatcher = _dispatcher(EventBus(), registry, {"search": client})

    result = await dispatcher.dispatch("web_search", {"query": "jarvis"})

    assert result.ok is True
    assert result.content == "4 results"
    assert client.calls == [("web_search", {"query": "jarvis"})]


async def test_dispatch_passes_through_structured_content():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(
        result=ToolCallResult(content="4 results", structured_content={"count": 4})
    )
    dispatcher = _dispatcher(EventBus(), registry, {"search": client})

    result = await dispatcher.dispatch("web_search", {})

    assert result.structured_content == {"count": 4}


async def test_dispatch_publishes_call_then_execute_then_outcome_in_order():
    registry = _registry_with(_enabled_tool())
    order = []

    class OrderTrackingClient:
        async def call_tool(self, name, arguments):
            order.append("execute")
            return ToolCallResult(content="ok")

    bus = EventBus()

    async def handler(event):
        order.append(f"event:{event.level.value}")

    bus.subscribe(SystemEvent, handler)
    dispatcher = _dispatcher(bus, registry, {"search": OrderTrackingClient()})

    await dispatcher.dispatch("web_search", {})

    assert order == ["event:active", "execute", "event:info"]


async def test_dispatch_reports_tool_reported_error_without_raising():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(result=ToolCallResult(content="boom", is_error=True))
    dispatcher = _dispatcher(EventBus(), registry, {"search": client})

    result = await dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert result.content == "boom"


async def test_dispatch_client_exception_degrades_to_an_error_result():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(exc=RuntimeError("subprocess died"))
    dispatcher = _dispatcher(EventBus(), registry, {"search": client})

    result = await dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert "subprocess died" in result.error


async def test_dispatch_client_exception_still_publishes_an_outcome_event():
    """A generic (non-transport) exception is a normal per-call failure,
    not a systemic problem - WARN, not ERROR (see the dedicated transport-
    vs-generic severity test below)."""
    registry = _registry_with(_enabled_tool())
    client = FakeClient(exc=RuntimeError("subprocess died"))
    bus = EventBus()
    events = await _collect(bus, SystemEvent)
    dispatcher = _dispatcher(bus, registry, {"search": client})

    await dispatcher.dispatch("web_search", {})

    assert len(events) == 2
    assert events[-1].level.value == "warn"


async def test_dispatch_transport_error_outcome_event_is_error_level():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(exc=McpTransportError("pipe broken"))
    bus = EventBus()
    events = await _collect(bus, SystemEvent)
    dispatcher = _dispatcher(bus, registry, {"search": client})

    await dispatcher.dispatch("web_search", {})

    assert events[-1].level.value == "error"


async def test_dispatch_transport_error_reports_to_on_transport_error():
    """Round 3 follow-up: only McpTransportError (a genuinely broken
    session/subprocess, per mcp_client.py's boundary) reaches
    on_transport_error - a plain ToolDispatchResult alone never reaches
    McpHost, so this is the only channel that can degrade the module."""
    registry = _registry_with(_enabled_tool())
    client = FakeClient(exc=McpTransportError("pipe broken"))
    reported = []

    async def on_transport_error(provider, exc):
        reported.append((provider, exc))

    dispatcher = _dispatcher(
        EventBus(), registry, {"search": client}, on_transport_error=on_transport_error
    )

    result = await dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert len(reported) == 1
    assert reported[0][0] == "search"
    assert isinstance(reported[0][1], McpTransportError)


async def test_dispatch_generic_exception_does_not_call_on_transport_error():
    """Round 3 follow-up repro: a normal per-call failure (e.g. the SDK's
    own McpError for a bad request or a timed-out call, simulated here by
    a plain RuntimeError) must only fail that one call - it must not be
    treated as transport death just because something was raised."""
    registry = _registry_with(_enabled_tool())
    client = FakeClient(exc=RuntimeError("bad arguments"))
    reported = []

    async def on_transport_error(provider, exc):
        reported.append((provider, exc))

    dispatcher = _dispatcher(
        EventBus(), registry, {"search": client}, on_transport_error=on_transport_error
    )

    result = await dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert "bad arguments" in result.error
    assert reported == []


async def test_dispatch_tool_reported_error_does_not_call_on_transport_error():
    """The isError-but-no-exception path is a normal tool outcome, not a
    transport failure - it must not trigger the same host-level reaction
    as a raised exception."""
    registry = _registry_with(_enabled_tool())
    client = FakeClient(result=ToolCallResult(content="boom", is_error=True))
    reported = []

    async def on_transport_error(provider, exc):
        reported.append((provider, exc))

    dispatcher = _dispatcher(
        EventBus(), registry, {"search": client}, on_transport_error=on_transport_error
    )

    await dispatcher.dispatch("web_search", {})

    assert reported == []


async def test_dispatch_cancellation_publishes_a_finished_event_and_reraises():
    """Review finding 6: asyncio.CancelledError does not subclass
    Exception, so it must be handled explicitly - a cancelled call must
    still get a correlated ToolCallFinished/SystemEvent pair, and
    cancellation itself must still propagate (never swallowed)."""
    registry = _registry_with(_enabled_tool())

    class CancellingClient:
        async def call_tool(self, name, arguments):
            raise asyncio.CancelledError()

    bus = EventBus()
    finished = await _collect(bus, ToolCallFinished)
    system_events = await _collect(bus, SystemEvent)
    dispatcher = _dispatcher(bus, registry, {"search": CancellingClient()})

    raised = False
    try:
        await dispatcher.dispatch("web_search", {})
    except asyncio.CancelledError:
        raised = True

    assert raised is True
    assert len(finished) == 1
    assert finished[0].ok is False
    assert len(system_events) == 2  # the initial "calling" event plus this outcome


async def test_dispatch_cancellation_still_releases_the_admission_slot():
    registry = _registry_with(_enabled_tool())

    class CancellingClient:
        async def call_tool(self, name, arguments):
            raise asyncio.CancelledError()

    admission = _Admission()
    dispatcher = _dispatcher(
        EventBus(), registry, {"search": CancellingClient()}, admission
    )

    with contextlib.suppress(asyncio.CancelledError):
        await dispatcher.dispatch("web_search", {})

    assert admission.inflight == 0


async def test_cancellation_after_started_event_still_publishes_correlated_outcome():
    """Once ToolCallStarted is visible, cancellation at any later await must
    produce exactly one ToolCallFinished for audit/watchdog consumers."""
    registry = _registry_with(_enabled_tool())
    client = FakeClient(result=ToolCallResult(content="unused"))
    bus = EventBus()
    started = await _collect(bus, ToolCallStarted)
    finished = await _collect(bus, ToolCallFinished)
    calling_event_entered = asyncio.Event()
    hold_calling_event = asyncio.Event()

    async def block_calling_system_event(event):
        if event.level.value == "active":
            calling_event_entered.set()
            await hold_calling_event.wait()

    bus.subscribe(SystemEvent, block_calling_system_event)
    dispatcher = _dispatcher(bus, registry, {"search": client})
    dispatch_task = asyncio.create_task(dispatcher.dispatch("web_search", {}))
    await calling_event_entered.wait()

    dispatch_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await dispatch_task

    assert len(started) == 1
    assert len(finished) == 1
    assert finished[0].correlation_id == started[0].correlation_id
    assert finished[0].ok is False
    assert finished[0].error == "cancelled"
    assert client.calls == []


# --- rejected dispatches must still publish an outcome (review finding 6) --


async def test_rejected_dispatch_publishes_a_system_event():
    bus = EventBus()
    events = await _collect(bus, SystemEvent)
    dispatcher = _dispatcher(
        bus, _registry_with(_enabled_tool()), {}, _Admission(admitting=False)
    )

    await dispatcher.dispatch("web_search", {"query": "x"})

    assert len(events) == 1
    assert events[0].level.value == "warn"


async def test_rejected_dispatch_publishes_a_typed_tool_call_finished_event():
    bus = EventBus()
    finished = await _collect(bus, ToolCallFinished)
    dispatcher = _dispatcher(
        bus, _registry_with(_enabled_tool()), {}, _Admission(admitting=False)
    )

    result = await dispatcher.dispatch("web_search", {"query": "x"})

    assert len(finished) == 1
    assert finished[0].ok is False
    assert finished[0].correlation_id == result.correlation_id
    assert finished[0].tool_name == "web_search"


async def test_rejected_dispatch_does_not_publish_a_started_event():
    bus = EventBus()
    started = await _collect(bus, ToolCallStarted)
    dispatcher = _dispatcher(
        bus, _registry_with(_enabled_tool()), {}, _Admission(admitting=False)
    )

    await dispatcher.dispatch("web_search", {})

    assert started == []


# --- localization (review round 2, finding 4) -------------------------------


async def test_rejection_ui_message_is_localized_and_has_no_embedded_english_reason():
    bus = EventBus()
    events = await _collect(bus, SystemEvent)
    dispatcher = _dispatcher(
        bus,
        _registry_with(_enabled_tool()),
        {},
        _Admission(admitting=False),
        ui_language="ru",
    )

    await dispatcher.dispatch("web_search", {})

    assert "Provider not available" not in events[0].message
    assert "недоступ" in events[0].message.lower()


async def test_rejection_ui_message_defaults_to_english():
    bus = EventBus()
    events = await _collect(bus, SystemEvent)
    dispatcher = _dispatcher(
        bus, _registry_with(_enabled_tool()), {}, _Admission(admitting=False)
    )

    await dispatcher.dispatch("web_search", {})

    assert "unavailable" in events[0].message.lower()


async def test_successful_call_ui_message_is_localized():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(result=ToolCallResult(content="ok"))
    bus = EventBus()
    events = await _collect(bus, SystemEvent)
    dispatcher = _dispatcher(bus, registry, {"search": client}, ui_language="ru")

    await dispatcher.dispatch("web_search", {"query": "jarvis"})

    assert any("Вызов инструмента" in event.message for event in events)
    assert any("завершён" in event.message for event in events)


# --- typed correlated contract (review finding 6, round 1) -----------------


async def test_successful_dispatch_shares_one_correlation_id_across_both_events():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(result=ToolCallResult(content="ok"))
    bus = EventBus()
    started = await _collect(bus, ToolCallStarted)
    finished = await _collect(bus, ToolCallFinished)
    dispatcher = _dispatcher(bus, registry, {"search": client})

    result = await dispatcher.dispatch("web_search", {"query": "jarvis"})

    assert len(started) == 1
    assert len(finished) == 1
    assert (
        started[0].correlation_id == finished[0].correlation_id == result.correlation_id
    )
    assert started[0].outbound_summary == finished[0].outbound_summary
    assert started[0].provider == "search"
    assert finished[0].duration_seconds >= 0


async def test_system_events_carry_the_same_correlation_id_as_the_typed_events():
    registry = _registry_with(_enabled_tool())
    client = FakeClient(result=ToolCallResult(content="ok"))
    bus = EventBus()
    system_events = await _collect(bus, SystemEvent)
    finished = await _collect(bus, ToolCallFinished)
    dispatcher = _dispatcher(bus, registry, {"search": client})

    await dispatcher.dispatch("web_search", {})

    assert all(
        event.correlation_id == finished[0].correlation_id for event in system_events
    )


def test_summarize_outbound_names_provider_tool_and_arguments():
    summary = summarize_outbound("search", "web_search", {"query": "jarvis"})

    assert summary == "search.web_search(query='jarvis')"
