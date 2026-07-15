"""Unit tests for StdioMcpClient's real SDK-adapter logic (review finding
8: fake-client tests elsewhere fully bypass this adapter, including its
riskiest logic - connection-owner cleanup, cross-task lifecycle, list_tools()
pagination, and CallToolResult mapping). No real subprocess or network:
mcp.client.stdio.stdio_client and mcp.ClientSession are monkeypatched with
plain fake async context managers shaped like the real SDK objects
(verified field names against the installed mcp 1.28.1's
Tool/ListToolsResult/CallToolResult.model_fields)."""

import asyncio

import anyio
import mcp
import mcp.client.stdio as stdio_module
import pytest

from jarvis.tools.mcp_client import McpTransportError, StdioMcpClient


class _FakeAsyncCtx:
    def __init__(self, value=None, enter_exc=None):
        self._value = value
        self._enter_exc = enter_exc
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        if self._enter_exc is not None:
            raise self._enter_exc
        self.entered = True
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True
        return False


class _TaskBoundAsyncCtx(_FakeAsyncCtx):
    """Models AnyIO contexts whose cancel scope must exit in its owner task."""

    def __init__(self, value=None):
        super().__init__(value=value)
        self._owner_task = None

    async def __aenter__(self):
        value = await super().__aenter__()
        self._owner_task = asyncio.current_task()
        return value

    async def __aexit__(self, exc_type, exc, tb):
        if asyncio.current_task() is not self._owner_task:
            raise RuntimeError("context exited from a different task")
        return await super().__aexit__(exc_type, exc, tb)


class _FakeSession:
    def __init__(
        self, pages=(), call_result=None, initialize_exc=None, call_tool_exc=None
    ):
        self._pages = list(pages)
        self._call_result = call_result
        self._initialize_exc = initialize_exc
        self._call_tool_exc = call_tool_exc
        self.list_tools_cursors: list = []
        self.call_tool_calls: list = []

    async def initialize(self):
        if self._initialize_exc is not None:
            raise self._initialize_exc

    async def list_tools(self, cursor=None):
        self.list_tools_cursors.append(cursor)
        return self._pages.pop(0)

    async def call_tool(self, name, arguments):
        self.call_tool_calls.append((name, arguments))
        if self._call_tool_exc is not None:
            raise self._call_tool_exc
        return self._call_result


class _Tool:
    def __init__(self, name, description="", schema=None):
        self.name = name
        self.description = description
        self.inputSchema = schema or {}


class _ListToolsResult:
    def __init__(self, tools, next_cursor=None):
        self.tools = tools
        self.nextCursor = next_cursor


class _CallToolResult:
    def __init__(self, content, is_error=False, structured=None):
        self.content = content
        self.isError = is_error
        self.structuredContent = structured


def _patch_transport(monkeypatch, stdio_ctx, session_ctx):
    monkeypatch.setattr(stdio_module, "stdio_client", lambda params: stdio_ctx)
    monkeypatch.setattr(mcp, "ClientSession", lambda *args, **kwargs: session_ctx)


def _connected_transport(monkeypatch, session):
    stdio_ctx = _FakeAsyncCtx(value=(object(), object()))
    session_ctx = _FakeAsyncCtx(value=session)
    _patch_transport(monkeypatch, stdio_ctx, session_ctx)
    return stdio_ctx, session_ctx


async def test_connect_initializes_the_session(monkeypatch):
    session = _FakeSession()
    stdio_ctx, session_ctx = _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server", ("--flag",))

    await client.connect()

    assert stdio_ctx.entered is True
    assert session_ctx.entered is True


async def test_connect_passes_command_and_args_to_stdio_params(monkeypatch):
    captured = {}

    def fake_stdio_client(params):
        captured["command"] = params.command
        captured["args"] = params.args
        return _FakeAsyncCtx(value=(object(), object()))

    monkeypatch.setattr(stdio_module, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(
        mcp, "ClientSession", lambda *a, **k: _FakeAsyncCtx(value=_FakeSession())
    )
    client = StdioMcpClient("search-server", ("-y", "pkg"))

    await client.connect()

    assert captured["command"] == "search-server"
    assert captured["args"] == ["-y", "pkg"]


async def test_connect_passes_server_specific_environment_to_stdio_params(monkeypatch):
    captured = {}

    def fake_stdio_client(params):
        captured["env"] = params.env
        return _FakeAsyncCtx(value=(object(), object()))

    monkeypatch.setattr(stdio_module, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(
        mcp, "ClientSession", lambda *a, **k: _FakeAsyncCtx(value=_FakeSession())
    )
    client = StdioMcpClient("qdrant-server", env={"QDRANT_READ_ONLY": "true"})

    await client.connect()

    assert captured["env"] == {"QDRANT_READ_ONLY": "true"}


async def test_connect_failure_during_initialize_closes_both_contexts(monkeypatch):
    session = _FakeSession(initialize_exc=RuntimeError("handshake failed"))
    stdio_ctx, session_ctx = _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")

    with pytest.raises(RuntimeError, match="handshake failed"):
        await client.connect()

    assert stdio_ctx.exited is True
    assert session_ctx.exited is True


async def test_connect_failure_entering_stdio_client_never_constructs_a_session(
    monkeypatch,
):
    stdio_ctx = _FakeAsyncCtx(enter_exc=OSError("no such command"))
    session_construction_calls = []

    def fake_session_factory(*args, **kwargs):
        session_construction_calls.append((args, kwargs))
        return _FakeAsyncCtx(value=_FakeSession())

    monkeypatch.setattr(stdio_module, "stdio_client", lambda params: stdio_ctx)
    monkeypatch.setattr(mcp, "ClientSession", fake_session_factory)
    client = StdioMcpClient("bad-command")

    with pytest.raises(OSError, match="no such command"):
        await client.connect()

    assert session_construction_calls == []
    # stdio_ctx.__aenter__() itself raised, so the connection owner never
    # entered it successfully and there is no matching __aexit__ call.
    assert stdio_ctx.exited is False


async def test_disconnect_before_connect_is_a_safe_no_op():
    client = StdioMcpClient("search-server")

    await client.disconnect()


async def test_disconnect_closes_the_exit_stack(monkeypatch):
    session = _FakeSession()
    stdio_ctx, session_ctx = _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    await client.disconnect()

    assert stdio_ctx.exited is True
    assert session_ctx.exited is True


async def test_connect_and_disconnect_may_be_requested_from_different_tasks(
    monkeypatch,
):
    """The official stdio transport owns an AnyIO task-group cancel scope.
    Startup and Control Center actions run in different asyncio tasks, so
    StdioMcpClient must keep context entry and exit inside one owner task."""
    session = _FakeSession()
    stdio_ctx = _TaskBoundAsyncCtx(value=(object(), object()))
    session_ctx = _TaskBoundAsyncCtx(value=session)
    _patch_transport(monkeypatch, stdio_ctx, session_ctx)
    client = StdioMcpClient("search-server")

    await asyncio.create_task(client.connect())
    await asyncio.create_task(client.disconnect())

    assert stdio_ctx.exited is True
    assert session_ctx.exited is True


async def test_list_tools_before_connect_raises_runtime_error():
    client = StdioMcpClient("search-server")

    with pytest.raises(RuntimeError, match="before connect"):
        await client.list_tools()


async def test_call_tool_before_connect_raises_runtime_error():
    client = StdioMcpClient("search-server")

    with pytest.raises(RuntimeError, match="before connect"):
        await client.call_tool("x", {})


async def test_list_tools_maps_name_description_and_schema(monkeypatch):
    session = _FakeSession(
        pages=[_ListToolsResult([_Tool("web_search", "desc", {"type": "object"})])]
    )
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    declarations = await client.list_tools()

    assert len(declarations) == 1
    assert declarations[0].name == "web_search"
    assert declarations[0].description == "desc"
    assert declarations[0].schema == {"type": "object"}


async def test_list_tools_defaults_none_description_to_empty_string(monkeypatch):
    session = _FakeSession(
        pages=[_ListToolsResult([_Tool("web_search", description=None)])]
    )
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    [declaration] = await client.list_tools()

    assert declaration.description == ""


async def test_list_tools_follows_pagination_across_multiple_pages(monkeypatch):
    session = _FakeSession(
        pages=[
            _ListToolsResult([_Tool("a")], next_cursor="page-2"),
            _ListToolsResult([_Tool("b")], next_cursor="page-3"),
            _ListToolsResult([_Tool("c")], next_cursor=None),
        ]
    )
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    declarations = await client.list_tools()

    assert [d.name for d in declarations] == ["a", "b", "c"]
    assert session.list_tools_cursors == [None, "page-2", "page-3"]


async def test_list_tools_single_page_stops_after_one_call(monkeypatch):
    session = _FakeSession(pages=[_ListToolsResult([_Tool("a")], next_cursor=None)])
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    await client.list_tools()

    assert session.list_tools_cursors == [None]


async def test_call_tool_maps_content_is_error_and_structured_content(monkeypatch):
    session = _FakeSession(
        call_result=_CallToolResult(
            content=["hit1", "hit2"], is_error=False, structured={"count": 2}
        )
    )
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    result = await client.call_tool("web_search", {"query": "jarvis"})

    assert result.content == ["hit1", "hit2"]
    assert result.is_error is False
    assert result.structured_content == {"count": 2}
    assert session.call_tool_calls == [("web_search", {"query": "jarvis"})]


async def test_call_tool_maps_is_error_true(monkeypatch):
    session = _FakeSession(call_result=_CallToolResult(content="boom", is_error=True))
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    result = await client.call_tool("web_search", {})

    assert result.is_error is True


# --- McpTransportError boundary (the user's own review of call_tool()) -----


@pytest.mark.parametrize(
    "transport_exc",
    [
        anyio.BrokenResourceError(),
        anyio.ClosedResourceError(),
        anyio.EndOfStream(),
        OSError("pipe closed"),
    ],
)
async def test_call_tool_wraps_transport_exceptions_as_mcp_transport_error(
    monkeypatch, transport_exc
):
    session = _FakeSession(call_tool_exc=transport_exc)
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    with pytest.raises(McpTransportError):
        await client.call_tool("web_search", {})


async def test_call_tool_transport_error_chains_the_original_exception(monkeypatch):
    original = anyio.BrokenResourceError()
    session = _FakeSession(call_tool_exc=original)
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    with pytest.raises(McpTransportError) as excinfo:
        await client.call_tool("web_search", {})

    assert excinfo.value.__cause__ is original


async def test_call_tool_does_not_wrap_a_normal_protocol_error(monkeypatch):
    """A non-transport exception (simulating the SDK's own McpError for a
    bad request or a timed-out call) must propagate unchanged - only the
    specific transport-exception family gets wrapped."""

    class FakeMcpError(Exception):
        pass

    protocol_error = FakeMcpError("invalid params")
    session = _FakeSession(call_tool_exc=protocol_error)
    _connected_transport(monkeypatch, session)
    client = StdioMcpClient("search-server")
    await client.connect()

    with pytest.raises(FakeMcpError):
        await client.call_tool("web_search", {})
