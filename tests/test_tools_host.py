import asyncio
import contextlib

from jarvis.core.bus import EventBus
from jarvis.core.config import McpServerSettings, McpSettings
from jarvis.tools.host import McpHost, McpModuleStatus, McpModuleStatusChanged
from jarvis.tools.mcp_client import McpTransportError, ToolCallResult, ToolDeclaration
from jarvis.ui.contract import SystemEvent


class FakeMcpClient:
    def __init__(self, tools=None, fail_connect=False, fail_disconnect=False):
        self.connected = False
        self.disconnect_called = False
        self._tools = tools or []
        self._fail_connect = fail_connect
        self._fail_disconnect = fail_disconnect

    async def connect(self):
        if self._fail_connect:
            raise RuntimeError("boom")
        self.connected = True

    async def disconnect(self):
        self.disconnect_called = True
        self.connected = False
        if self._fail_disconnect:
            raise RuntimeError("disconnect failed")

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments):
        raise NotImplementedError


def _factory(clients_by_command: dict):
    def factory(server: McpServerSettings):
        return clients_by_command[server.command]

    return factory


async def _events(bus: EventBus) -> list:
    events: list = []

    async def handler(event):
        events.append(event)

    bus.subscribe(SystemEvent, handler)
    return events


def _factory_that_must_not_be_called(server: McpServerSettings):
    raise AssertionError("client_factory must not run before enable()")


async def test_mcp_host_is_off_and_inert_at_construction():
    """Constructing McpHost never spawns anything by itself, regardless of
    whether [mcp].enabled is true in settings - only enable() does. This
    is what lets jarvis.app.build_app() always construct a real McpHost
    (see tests/test_main.py) without violating "off equals the capability
    does not exist"."""
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    host = McpHost(
        EventBus(), settings, client_factory=_factory_that_must_not_be_called
    )

    assert host.status == McpModuleStatus.OFF
    assert host.enabled is False
    assert host.registry.all() == ()


async def test_enable_connects_every_enabled_server_and_populates_registry():
    settings = McpSettings(
        enabled=True,
        servers={
            "search": McpServerSettings(command="search-server"),
            "db": McpServerSettings(command="db-server"),
        },
    )
    search_client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    db_client = FakeMcpClient(tools=[ToolDeclaration("query", "d", {})])
    factory = _factory({"search-server": search_client, "db-server": db_client})
    host = McpHost(EventBus(), settings, client_factory=factory)

    await host.enable()

    assert host.status == McpModuleStatus.ON
    assert search_client.connected is True
    assert db_client.connected is True
    assert {t.name for t in host.registry.all()} == {"web_search", "query"}


async def test_enable_skips_per_server_disabled_servers():
    settings = McpSettings(
        enabled=True,
        servers={"search": McpServerSettings(command="search-server", enabled=False)},
    )
    client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)

    await host.enable()

    assert client.connected is False
    assert host.registry.all() == ()
    assert host.status == McpModuleStatus.ON


async def test_enable_is_idempotent():
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient()
    calls = []

    def factory(server):
        calls.append(server)
        return client

    host = McpHost(EventBus(), settings, client_factory=factory)

    await host.enable()
    await host.enable()

    assert len(calls) == 1


async def test_concurrent_enable_calls_only_connect_once():
    """Review finding 2 repro: two concurrent enable() calls used to both
    pass the pre-lock status check and each construct/connect their own
    client, with the second silently overwriting the first in _clients -
    leaking the first client's subprocess forever. The lock serializes
    them so the second call's status check always sees the first call's
    already-terminal status."""
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    created = []

    def factory(server):
        client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
        created.append(client)
        return client

    host = McpHost(EventBus(), settings, client_factory=factory)

    await asyncio.gather(host.enable(), host.enable())

    assert len(created) == 1
    assert host.status == McpModuleStatus.ON


async def test_disable_waits_for_an_in_progress_enable_to_finish():
    connecting = asyncio.Event()
    proceed = asyncio.Event()

    class SlowClient(FakeMcpClient):
        async def connect(self):
            connecting.set()
            await proceed.wait()
            await super().connect()

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = SlowClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)

    enable_task = asyncio.create_task(host.enable())
    await connecting.wait()
    assert host.status == McpModuleStatus.CONNECTING

    disable_task = asyncio.create_task(host.disable())
    await asyncio.sleep(0)
    # disable() is blocked behind the same lock enable() is holding - it
    # must not tear down a connection that is still being established.
    assert host.status == McpModuleStatus.CONNECTING

    proceed.set()
    await enable_task
    await disable_task

    assert host.status == McpModuleStatus.OFF


async def test_disable_disconnects_every_client_and_clears_registry():
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()

    await host.disable()

    assert host.status == McpModuleStatus.OFF
    assert client.disconnect_called is True
    assert host.registry.all() == ()


async def test_disable_when_never_enabled_is_a_safe_no_op():
    host = McpHost(EventBus(), McpSettings())

    await host.disable()

    assert host.status == McpModuleStatus.OFF


async def test_disable_continues_disconnecting_remaining_servers_after_one_fails():
    """Review finding 3: a raising disconnect() used to abort the whole
    teardown loop, leaving every later server connected and the module
    stuck mid-teardown."""
    settings = McpSettings(
        enabled=True,
        servers={
            "a": McpServerSettings(command="a-cmd"),
            "b": McpServerSettings(command="b-cmd"),
        },
    )
    client_a = FakeMcpClient(
        tools=[ToolDeclaration("tool_a", "d", {})], fail_disconnect=True
    )
    client_b = FakeMcpClient(tools=[ToolDeclaration("tool_b", "d", {})])
    factory = _factory({"a-cmd": client_a, "b-cmd": client_b})
    host = McpHost(EventBus(), settings, client_factory=factory)
    await host.enable()

    await host.disable()

    assert client_a.disconnect_called is True
    assert client_b.disconnect_called is True
    assert host.status == McpModuleStatus.OFF
    assert host.registry.all() == ()


async def test_disable_reports_a_disconnect_error_as_a_system_event():
    settings = McpSettings(
        enabled=True, servers={"a": McpServerSettings(command="a-cmd")}
    )
    client = FakeMcpClient(
        tools=[ToolDeclaration("tool_a", "d", {})], fail_disconnect=True
    )
    bus = EventBus()
    events = await _events(bus)
    host = McpHost(bus, settings, client_factory=lambda s: client)
    await host.enable()

    await host.disable()

    assert any(event.level.value == "error" for event in events)


async def test_list_tools_failure_after_successful_connect_disconnects_the_client():
    """Review finding 3: connect() succeeding but list_tools() raising
    used to publish an error and simply return, never calling
    disconnect() - leaking the now-connected-but-unusable subprocess."""

    class ListToolsFailsClient(FakeMcpClient):
        async def list_tools(self):
            raise RuntimeError("boom")

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = ListToolsFailsClient()
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)

    await host.enable()

    # FakeMcpClient.disconnect() itself flips connected back to False -
    # disconnect_called is the signal that cleanup actually ran instead of
    # leaking the connected-but-unusable client.
    assert client.disconnect_called is True
    assert client.connected is False
    assert host.registry.all() == ()
    assert host.status == McpModuleStatus.DEGRADED


async def test_enable_cancellation_during_tool_discovery_disconnects_and_returns_off():
    """Cancellation after connect() but before registration must not lose
    the connected client outside _clients or leave the host in CONNECTING."""
    listing = asyncio.Event()
    never = asyncio.Event()

    class SlowListClient(FakeMcpClient):
        async def list_tools(self):
            listing.set()
            await never.wait()
            return []

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = SlowListClient()
    host = McpHost(EventBus(), settings, client_factory=lambda server: client)
    enable_task = asyncio.create_task(host.enable())
    await listing.wait()

    enable_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await enable_task

    assert client.disconnect_called is True
    assert client.connected is False
    assert host.status == McpModuleStatus.OFF
    assert host.registry.all() == ()


async def test_failing_server_degrades_honestly_without_breaking_enable():
    settings = McpSettings(
        enabled=True,
        servers={
            "search": McpServerSettings(command="ok-server"),
            "broken": McpServerSettings(command="broken-server"),
        },
    )
    ok_client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    broken_client = FakeMcpClient(fail_connect=True)
    factory = _factory({"ok-server": ok_client, "broken-server": broken_client})
    bus = EventBus()
    events = await _events(bus)
    host = McpHost(bus, settings, client_factory=factory)

    await host.enable()

    assert host.status == McpModuleStatus.DEGRADED
    assert {t.name for t in host.registry.all()} == {"web_search"}
    assert any(event.level.value == "error" for event in events)


async def test_all_servers_failing_still_reports_degraded_not_a_clean_on():
    """Review finding 1: every configured server failing to connect used
    to still leave the module reporting a plain, healthy-looking
    enabled=True."""
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="broken")}
    )
    client = FakeMcpClient(fail_connect=True)
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)

    await host.enable()

    assert host.status == McpModuleStatus.DEGRADED
    assert host.enabled is True
    assert host.registry.all() == ()


async def test_tool_name_collision_marks_the_module_degraded():
    settings = McpSettings(
        enabled=True,
        servers={
            "a": McpServerSettings(command="a-cmd"),
            "b": McpServerSettings(command="b-cmd"),
        },
    )
    client_a = FakeMcpClient(tools=[ToolDeclaration("lookup", "d", {})])
    client_b = FakeMcpClient(tools=[ToolDeclaration("lookup", "d", {})])
    factory = _factory({"a-cmd": client_a, "b-cmd": client_b})
    host = McpHost(EventBus(), settings, client_factory=factory)

    await host.enable()

    assert host.status == McpModuleStatus.DEGRADED
    assert host.registry.get("lookup").provider == "a"


async def test_toggle_publishes_enabled_and_disabled_events():
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient()
    bus = EventBus()
    events = await _events(bus)
    host = McpHost(bus, settings, client_factory=lambda s: client, ui_language="ru")

    await host.enable()
    await host.disable()

    messages = [event.message for event in events]
    assert any("включ" in message.lower() for message in messages)
    assert any("выключ" in message.lower() for message in messages)


async def test_toggle_events_default_to_english():
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient()
    bus = EventBus()
    events = await _events(bus)
    host = McpHost(bus, settings, client_factory=lambda s: client)

    await host.enable()
    await host.disable()

    messages = [event.message for event in events]
    assert any("enabled" in message.lower() for message in messages)
    assert any("disabled" in message.lower() for message in messages)


async def test_reenable_after_disable_reconnects():
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)

    await host.enable()
    await host.disable()
    await host.enable()

    assert host.status == McpModuleStatus.ON
    assert {t.name for t in host.registry.all()} == {"web_search"}


async def test_set_tool_enabled_through_the_real_host_reaches_the_dispatcher():
    """Review finding 6: the disabled-tool dispatch behavior must be
    reachable through the real production path (McpHost.set_tool_enabled),
    not only through a hand-constructed RegisteredTool in a test."""
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()

    changed = host.set_tool_enabled("web_search", False)
    result = await host.dispatcher.dispatch("web_search", {})

    assert changed is True
    assert result.ok is False
    assert "disabled" in result.error.lower()


async def test_dispatch_is_rejected_once_disable_has_started():
    """Review round 2 finding 1 repro: a dispatch() call that arrives
    while disable() is tearing down must be rejected before it can reach
    a disconnecting client, never silently routed to it."""
    disconnecting = asyncio.Event()
    proceed = asyncio.Event()

    class SlowDisconnectClient(FakeMcpClient):
        async def disconnect(self):
            disconnecting.set()
            await proceed.wait()
            await super().disconnect()

        async def call_tool(self, name, arguments):
            raise AssertionError("call_tool must not run on a disconnecting client")

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = SlowDisconnectClient(tools=[ToolDeclaration("lookup", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()

    disable_task = asyncio.create_task(host.disable())
    await disconnecting.wait()

    result = await host.dispatcher.dispatch("lookup", {})

    assert result.ok is False
    assert result.error == "MCP is disabled"

    proceed.set()
    await disable_task


async def test_disable_waits_for_an_admitted_dispatch_before_disconnecting():
    """The other half of finding 1: a dispatch() call admitted just
    before disable() closes the gate must finish (or at least release its
    client reference) before the actual disconnect runs."""
    calling = asyncio.Event()
    proceed = asyncio.Event()
    order: list[str] = []

    class SlowCallClient(FakeMcpClient):
        async def call_tool(self, name, arguments):
            calling.set()
            order.append("call_tool_started")
            await proceed.wait()
            order.append("call_tool_finished")
            return ToolCallResult(content="ok")

        async def disconnect(self):
            order.append("disconnect")
            await super().disconnect()

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = SlowCallClient(tools=[ToolDeclaration("lookup", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()

    dispatch_task = asyncio.create_task(host.dispatcher.dispatch("lookup", {}))
    await calling.wait()

    disable_task = asyncio.create_task(host.disable())
    await asyncio.sleep(0)
    # disable() must be blocked waiting for the in-flight call, not
    # already disconnecting underneath it.
    assert "disconnect" not in order

    proceed.set()
    await dispatch_task
    await disable_task

    assert order == ["call_tool_started", "call_tool_finished", "disconnect"]


async def test_mcp_module_status_changed_published_on_every_transition():
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    bus = EventBus()
    changes = []

    async def handler(event):
        changes.append(event.status)

    bus.subscribe(McpModuleStatusChanged, handler)
    host = McpHost(bus, settings, client_factory=lambda s: client)

    await host.enable()
    await host.disable()

    assert changes == [
        McpModuleStatus.CONNECTING,
        McpModuleStatus.ON,
        McpModuleStatus.DISCONNECTING,
        McpModuleStatus.OFF,
    ]


async def test_mcp_module_status_changed_reports_degraded_on_partial_failure():
    settings = McpSettings(
        enabled=True,
        servers={
            "search": McpServerSettings(command="ok-server"),
            "broken": McpServerSettings(command="broken-server"),
        },
    )
    factory = _factory(
        {
            "ok-server": FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})]),
            "broken-server": FakeMcpClient(fail_connect=True),
        }
    )
    bus = EventBus()
    changes = []

    async def handler(event):
        changes.append(event.status)

    bus.subscribe(McpModuleStatusChanged, handler)
    host = McpHost(bus, settings, client_factory=factory)

    await host.enable()

    assert changes == [McpModuleStatus.CONNECTING, McpModuleStatus.DEGRADED]


async def test_transport_error_through_real_host_degrades_and_clears_tools():
    """Review finding 3, exercised through the real host + dispatcher, not
    just the interception-layer unit test. Must raise McpTransportError
    specifically (round 3 follow-up) - a generic exception is a normal
    per-call failure and must not degrade the module (see the sibling
    test below)."""

    class DyingClient(FakeMcpClient):
        async def call_tool(self, name, arguments):
            raise McpTransportError("connection reset")

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = DyingClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()
    assert host.status == McpModuleStatus.ON

    result = await host.dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert host.status == McpModuleStatus.DEGRADED
    assert host.registry.all() == ()


async def test_generic_call_exception_through_real_host_does_not_degrade():
    """The sibling of the test above: a normal per-call exception (not
    McpTransportError) must fail only that call - the module stays ON and
    the provider's tools stay in the registry."""

    class FlakyClient(FakeMcpClient):
        async def call_tool(self, name, arguments):
            raise RuntimeError("bad arguments")

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FlakyClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()

    result = await host.dispatcher.dispatch("web_search", {})

    assert result.ok is False
    assert host.status == McpModuleStatus.ON
    assert {t.name for t in host.registry.all()} == {"web_search"}


async def test_transport_error_does_not_downgrade_from_off():
    """A stray call after disable() (e.g. a race in a caller) must not
    resurrect a DEGRADED status once the module is off - _on_transport_
    error only escalates from ON, not from every status."""
    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = FakeMcpClient(tools=[ToolDeclaration("web_search", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()
    await host.disable()

    # Bypass the dispatcher's own "MCP is disabled" admission check to
    # exercise _on_transport_error directly, as if it fired concurrently
    # with a disable() that already completed.
    await host._on_transport_error("search", RuntimeError("late failure"))

    assert host.status == McpModuleStatus.OFF


async def test_dispatch_from_status_changed_on_handler_is_admitted():
    """Review round 3 finding 1 repro: a subscriber reacting to the ON
    event the instant it fires must see a module that is already
    admitting dispatches, not one that still rejects with "MCP is
    disabled"."""

    class WorkingClient(FakeMcpClient):
        async def call_tool(self, name, arguments):
            return ToolCallResult(content="ok")

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = WorkingClient(tools=[ToolDeclaration("web_search", "d", {})])
    bus = EventBus()
    host = McpHost(bus, settings, client_factory=lambda s: client)
    results = []

    async def handler(event):
        if event.status == McpModuleStatus.ON:
            results.append(await host.dispatcher.dispatch("web_search", {}))

    bus.subscribe(McpModuleStatusChanged, handler)

    await host.enable()

    assert len(results) == 1
    assert results[0].error != "MCP is disabled"


async def test_status_is_disconnecting_during_the_drain_wait():
    """Review round 3 finding 1 repro: while disable() waits for an
    in-flight dispatch to finish, .status must already report
    DISCONNECTING - a stale ON/DEGRADED here would no longer match the
    fact that admission is already closed."""
    calling = asyncio.Event()
    proceed = asyncio.Event()

    class SlowCallClient(FakeMcpClient):
        async def call_tool(self, name, arguments):
            calling.set()
            await proceed.wait()
            return ToolCallResult(content="ok")

    settings = McpSettings(
        enabled=True, servers={"search": McpServerSettings(command="c")}
    )
    client = SlowCallClient(tools=[ToolDeclaration("lookup", "d", {})])
    host = McpHost(EventBus(), settings, client_factory=lambda s: client)
    await host.enable()

    dispatch_task = asyncio.create_task(host.dispatcher.dispatch("lookup", {}))
    await calling.wait()

    disable_task = asyncio.create_task(host.disable())
    await asyncio.sleep(0)

    assert host.status == McpModuleStatus.DISCONNECTING

    proceed.set()
    await dispatch_task
    await disable_task
