import asyncio
import contextlib
import gc
import inspect
import json
import logging
import socket
import time
from collections.abc import AsyncIterator

import httpx
import pytest
import uvicorn
from _mcp_mode_support import (
    FakeVoiceGuide,
    RunningMcpServer,
    ServerStatusLog,
    serving_mcp_server,
)
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.streamable_http import StreamableHTTPServerTransport

from jarvis.core.bus import EventBus
from jarvis.core.config import McpModeSettings
from jarvis.dialog.voice_guide import (
    VoiceGuideRejection,
    VoiceGuideRequest,
)
from jarvis.journal.external_canvas import ExternalCanvasCaller, SpeechOrigin
from jarvis.mcp_mode.server import (
    BearerTokenMiddleware,
    McpModeServer,
    McpPortUnavailableError,
    McpServerState,
    McpServerStatusChanged,
    SpeakQueue,
    bind_mcp_listener,
    build_speak_mcp,
    prepare_mcp_mode_server,
)
from jarvis.mcp_mode.token import McpTokenFileError

TOKEN = "test-token-6b1f0c9d-do-not-log"
_SETTINGS = McpModeSettings(
    max_canvas_chars=40, max_spoken_text_chars=30, max_guidance_chars=20
)
_CLIENT_INFO = types.Implementation(name="test-client", version="1.2.3")
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "raw", "version": "1"},
    },
}
_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _serving(
    voice_guide: FakeVoiceGuide, settings: McpModeSettings = _SETTINGS
) -> AsyncIterator[RunningMcpServer]:
    def build(bus: EventBus) -> McpModeServer:
        return McpModeServer(
            listener=bind_mcp_listener(0),
            token=TOKEN,
            settings=settings,
            voice_guide=voice_guide,
            bus=bus,
        )

    return serving_mcp_server(build=build)


@contextlib.asynccontextmanager
async def _client(
    url: str, *, on_response=None, terminate_on_close: bool = True
) -> AsyncIterator[tuple[ClientSession, object]]:
    hooks = {"response": [on_response]} if on_response is not None else {}
    http = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10, event_hooks=hooks
    )
    async with (
        http,
        streamable_http_client(
            url, http_client=http, terminate_on_close=terminate_on_close
        ) as (read, write, session_id),
        ClientSession(read, write, client_info=_CLIENT_INFO) as session,
    ):
        await session.initialize()
        yield session, session_id


async def _speak(url: str, **arguments: str) -> types.CallToolResult:
    async with _client(url) as (session, _):
        return await asyncio.wait_for(session.call_tool("speak", arguments), 5)


def _payload(result: types.CallToolResult) -> dict[str, object]:
    assert result.isError is False
    assert isinstance(result.content[0], types.TextContent)
    return json.loads(result.content[0].text)


def _error_text(result: types.CallToolResult) -> str:
    assert result.isError is True
    assert isinstance(result.content[0], types.TextContent)
    return result.content[0].text


def _build_server(listener: socket.socket) -> McpModeServer:
    return McpModeServer(
        listener=listener,
        token=TOKEN,
        settings=_SETTINGS,
        voice_guide=FakeVoiceGuide(),
        bus=EventBus(),
    )


# --- authentication and transport security -----------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": TOKEN}],
)
async def test_a_request_without_the_right_bearer_token_gets_401(headers):
    guide = FakeVoiceGuide()
    async with _serving(guide) as running, httpx.AsyncClient() as http:
        response = await http.post(
            running.url, json=_INITIALIZE, headers={**_JSON_HEADERS, **headers}
        )

    assert response.status_code == 401
    assert TOKEN not in response.text
    assert guide.requests == []


async def test_an_unauthorized_tool_call_never_reaches_the_voice_guide():
    guide = FakeVoiceGuide()
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "speak", "arguments": {"canvas": "An answer."}},
    }
    async with _serving(guide) as running, httpx.AsyncClient() as http:
        response = await http.post(
            running.url,
            json=call,
            headers={**_JSON_HEADERS, "Authorization": "Bearer wrong-token"},
        )

    assert response.status_code == 401
    assert guide.requests == []


async def test_the_bearer_scheme_is_case_insensitive():
    async with _serving(FakeVoiceGuide()) as running, httpx.AsyncClient() as http:
        response = await http.post(
            running.url,
            json=_INITIALIZE,
            headers={**_JSON_HEADERS, "Authorization": f"bearer {TOKEN}"},
        )

    assert response.status_code == 200


async def test_a_foreign_host_header_is_rejected_even_with_a_valid_token():
    async with _serving(FakeVoiceGuide()) as running, httpx.AsyncClient() as http:
        response = await http.post(
            running.url,
            json=_INITIALIZE,
            headers={
                **_JSON_HEADERS,
                "Authorization": f"Bearer {TOKEN}",
                "Host": "evil.example:80",
            },
        )

    assert response.status_code == 421


def test_the_token_is_absent_from_the_repr_and_str_of_server_objects():
    async def _app(scope, receive, send):
        del scope, receive, send

    middleware = BearerTokenMiddleware(_app, TOKEN)
    with bind_mcp_listener(0) as listener:
        server = _build_server(listener)

    for value in (middleware, server):
        assert TOKEN not in repr(value)
        assert TOKEN not in str(value)
        assert TOKEN not in repr(vars(value))


# --- the speak tool -----------------------------------------------------------


async def test_the_server_lists_exactly_the_speak_tool_with_its_schema():
    async with (
        _serving(FakeVoiceGuide()) as running,
        _client(running.url) as (
            session,
            _,
        ),
    ):
        listed = await session.list_tools()

    assert [tool.name for tool in listed.tools] == ["speak"]
    schema = listed.tools[0].inputSchema
    assert schema["required"] == ["canvas"]
    assert set(schema["properties"]) == {"canvas", "spoken_text", "guidance"}
    assert schema["properties"]["canvas"]["type"] == "string"
    for optional in ("spoken_text", "guidance"):
        prop = schema["properties"][optional]
        assert {"type": "string"} in prop["anyOf"]
        assert prop["default"] is None


async def test_the_tool_description_covers_what_the_caller_must_know():
    async with (
        _serving(FakeVoiceGuide()) as running,
        _client(running.url) as (
            session,
            _,
        ),
    ):
        listed = await session.list_tools()

    description = listed.tools[0].description or ""
    for fact in ("journal", "queued", "file:line", "spoken_text", "guidance"):
        assert fact in description
    for limit in (40, 30, 20):
        assert str(limit) in description


async def test_a_call_enqueues_one_request_carrying_the_caller_identity():
    guide = FakeVoiceGuide()
    async with (
        _serving(guide) as running,
        _client(running.url) as (
            session,
            session_id,
        ),
    ):
        await session.call_tool("speak", {"canvas": "An answer."})
        expected_session_id = session_id()

    assert expected_session_id is not None
    assert guide.requests == [
        VoiceGuideRequest(
            canvas="An answer.",
            caller=ExternalCanvasCaller(
                name="test-client",
                version="1.2.3",
                transport_session_id=expected_session_id,
            ),
        )
    ]


def test_the_server_sees_only_a_synchronous_enqueue_so_it_cannot_wait_for_speech():
    public = {name for name in vars(SpeakQueue) if not name.startswith("_")}

    assert public == {"enqueue"}
    assert not inspect.iscoroutinefunction(SpeakQueue.enqueue)


async def test_a_call_returns_the_queue_position_and_origin_it_was_given():
    guide = FakeVoiceGuide(origin=SpeechOrigin.VERBATIM)
    async with _serving(guide) as running:
        result = await _speak(running.url, canvas="An answer.")

    assert _payload(result) == {
        "status": "queued",
        "position": 1,
        "speech_origin": "verbatim",
    }


async def test_a_queued_result_carries_the_same_payload_as_structured_content():
    async with _serving(FakeVoiceGuide()) as running:
        result = await _speak(running.url, canvas="An answer.")

    assert result.structuredContent == _payload(result)


async def test_guidance_with_spoken_text_is_queued_with_guidance_ignored():
    async with _serving(FakeVoiceGuide(origin=SpeechOrigin.CALLER)) as running:
        result = await _speak(
            running.url, canvas="An answer.", spoken_text="Read.", guidance="Brief."
        )

    assert _payload(result) == {
        "status": "queued",
        "position": 1,
        "speech_origin": "caller",
        "guidance_ignored": True,
    }


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"canvas": "   "}, "empty_canvas"),
        ({"canvas": "x" * 41}, "canvas_too_long"),
        ({"canvas": "ok", "spoken_text": " "}, "empty_spoken_text"),
        ({"canvas": "ok", "spoken_text": "x" * 31}, "spoken_text_too_long"),
        ({"canvas": "ok", "guidance": "x" * 21}, "guidance_too_long"),
    ],
)
async def test_an_invalid_call_is_a_tool_error_starting_with_its_code(arguments, code):
    guide = FakeVoiceGuide()
    async with _serving(guide) as running:
        result = await _speak(running.url, **arguments)

    assert _error_text(result).startswith(f"{code}: ")
    assert guide.requests == []


@pytest.mark.parametrize(
    ("rejection", "code"),
    [
        (VoiceGuideRejection.QUEUE_FULL, "queue_full"),
        (VoiceGuideRejection.CLOSED, "closed"),
    ],
)
async def test_a_rejected_enqueue_is_a_tool_error_starting_with_its_code(
    rejection, code
):
    async with _serving(FakeVoiceGuide(rejection)) as running:
        result = await _speak(running.url, canvas="An answer.")

    assert _error_text(result).startswith(f"{code}: ")


# --- listener ------------------------------------------------------------------


def test_the_listener_binds_loopback_only():
    listener = bind_mcp_listener(0)
    try:
        assert listener.getsockname()[0] == "127.0.0.1"
    finally:
        listener.close()


def test_a_port_in_use_fails_with_the_port_and_its_config_key():
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = holder.getsockname()[1]
    try:
        with pytest.raises(McpPortUnavailableError) as raised:
            bind_mcp_listener(port)
    finally:
        holder.close()

    assert str(port) in str(raised.value)
    assert "[mcp_mode].port" in str(raised.value)


# --- lifecycle -------------------------------------------------------------------


async def test_the_server_publishes_listening_with_its_port_then_stopped():
    async with _serving(FakeVoiceGuide()) as running:
        port = running.server.port

    assert running.status.events == [
        McpServerStatusChanged(McpServerState.LISTENING, port=port),
        McpServerStatusChanged(McpServerState.STOPPED),
    ]


async def test_cancelling_during_startup_still_shuts_the_server_down():
    bus = EventBus()
    status = ServerStatusLog(bus)
    server = McpModeServer(
        listener=bind_mcp_listener(0),
        token=TOKEN,
        settings=_SETTINGS,
        voice_guide=FakeVoiceGuide(),
        bus=bus,
    )
    task = server.start()
    await asyncio.sleep(0)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    await asyncio.sleep(0)

    assert [event.state for event in status.events] == [
        McpServerState.LISTENING,
        McpServerState.STOPPED,
    ]
    assert asyncio.all_tasks() == {asyncio.current_task()}
    bind_mcp_listener(server.port).close()


async def test_cancelling_the_server_ends_its_task_as_cancelled():
    async with _serving(FakeVoiceGuide()) as running:
        pass

    assert running.task.cancelled()


async def test_a_server_that_cannot_serve_publishes_failed_and_raises():
    bus = EventBus()
    status = ServerStatusLog(bus)
    listener = bind_mcp_listener(0)
    server = McpModeServer(
        listener=listener,
        token=TOKEN,
        settings=_SETTINGS,
        voice_guide=FakeVoiceGuide(),
        bus=bus,
    )
    listener.close()

    with pytest.raises(OSError):
        await asyncio.wait_for(server.start(), 5)

    assert [event.state for event in status.events] == [McpServerState.FAILED]
    assert status.events[0].reason


async def test_a_server_that_cannot_serve_leaves_no_task_running():
    listener = bind_mcp_listener(0)
    server = _build_server(listener)
    listener.close()

    with pytest.raises(OSError):
        await asyncio.wait_for(server.start(), 5)
    await asyncio.sleep(0)

    assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_stopping_with_an_open_session_stream_is_fast_clean_and_frees_the_port(
    caplog,
):
    caplog.set_level(logging.DEBUG)
    stream_opened = asyncio.Event()

    async def on_response(response: httpx.Response) -> None:
        if response.request.method == "GET" and response.status_code == 200:
            stream_opened.set()

    measured: dict[str, float] = {}
    async with _serving(FakeVoiceGuide()) as running:
        port = running.server.port
        # The client outlives its server here, so its own teardown may fail.
        with contextlib.suppress(Exception):
            async with _client(
                running.url, on_response=on_response, terminate_on_close=False
            ):
                await asyncio.wait_for(stream_opened.wait(), 5)
                started = time.perf_counter()
                await running.stop()
                measured["elapsed"] = time.perf_counter() - started
    server_errors = [
        record
        for record in caplog.records
        if record.levelno >= logging.ERROR and not record.name.startswith("mcp.client")
    ]

    assert measured["elapsed"] < 1.0
    assert server_errors == []
    bind_mcp_listener(port).close()


async def test_the_token_appears_in_no_log_record(caplog):
    caplog.set_level(logging.DEBUG)

    async with _serving(FakeVoiceGuide()) as running, httpx.AsyncClient() as http:
        await _speak(running.url, canvas="An answer.")
        await http.post(
            running.url,
            json=_INITIALIZE,
            headers={**_JSON_HEADERS, "Authorization": "Bearer wrong"},
        )

    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert TOKEN not in str(record.args)


# --- logging -----------------------------------------------------------------------


def test_building_the_server_keeps_configured_root_logging_unchanged():
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level

    with bind_mcp_listener(0) as listener:
        _build_server(listener)

    assert root.handlers == handlers_before
    assert root.level == level_before


def test_building_the_server_installs_no_root_handler_when_there_is_none(
    monkeypatch,
):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    level_before = root.level

    with bind_mcp_listener(0) as listener:
        _build_server(listener)

    assert root.handlers == []
    assert root.level == level_before


# --- prepare -----------------------------------------------------------------------


async def test_prepare_returns_a_server_on_the_configured_port_and_token(tmp_path):
    token_file = tmp_path / "mcp_mode.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    settings = McpModeSettings(port=free_port, token_file=str(token_file))
    bus = EventBus()
    status = ServerStatusLog(bus)

    server = prepare_mcp_mode_server(settings, FakeVoiceGuide(), bus)
    running = RunningMcpServer(
        server=server, task=server.start(), bus=bus, status=status
    )
    try:
        await asyncio.wait_for(status.listening.wait(), 5)
        result = await _speak(running.url, canvas="An answer.")
    finally:
        await running.stop()

    assert server.port == free_port
    assert _payload(result)["status"] == "queued"


def test_prepare_fails_on_a_broken_token_file_without_binding_the_port(tmp_path):
    token_file = tmp_path / "mcp_mode.token"
    token_file.write_text("", encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    settings = McpModeSettings(port=free_port, token_file=str(token_file))

    with pytest.raises(McpTokenFileError) as raised:
        prepare_mcp_mode_server(settings, FakeVoiceGuide(), EventBus())

    assert raised.value.token_file == token_file
    bind_mcp_listener(free_port).close()


def test_a_port_error_carries_its_port():
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        with pytest.raises(McpPortUnavailableError) as raised:
            bind_mcp_listener(port)
    finally:
        holder.close()

    assert raised.value.port == port


# --- robustness --------------------------------------------------------------------

_SERVER_LOGGER = "jarvis.mcp_mode.server"


def _running_tasks_besides_sse_watcher() -> set[asyncio.Task]:
    # sse-starlette starts one shutdown poller per event loop and never ends it.
    return {
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and task.get_coro().__name__ != "_shutdown_watcher"
    }


async def _until(condition, timeout: float = 5) -> None:
    deadline = time.perf_counter() + timeout
    while not condition():
        if time.perf_counter() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


def test_the_session_manager_bounds_idle_sessions_and_their_number():
    mcp = build_speak_mcp(_SETTINGS, FakeVoiceGuide())
    mcp.streamable_http_app()

    assert mcp.session_manager.session_idle_timeout == 1800
    assert mcp.session_manager.max_sessions == 10000


async def test_cancelling_the_server_task_before_it_runs_releases_the_port():
    listener = bind_mcp_listener(0)
    port = listener.getsockname()[1]
    task = _build_server(listener).start()

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    bind_mcp_listener(port).close()


@pytest.mark.parametrize("further_cancels", [1, 2])
async def test_further_cancels_during_shutdown_do_not_abort_it(further_cancels):
    stream_opened = asyncio.Event()

    async def on_response(response: httpx.Response) -> None:
        if response.request.method == "GET" and response.status_code == 200:
            stream_opened.set()

    async with _serving(FakeVoiceGuide()) as running:
        port = running.server.port
        # The client outlives its server here, so its own teardown may fail.
        with contextlib.suppress(Exception):
            async with _client(
                running.url, on_response=on_response, terminate_on_close=False
            ):
                await asyncio.wait_for(stream_opened.wait(), 5)
                running.task.cancel()
                for _ in range(further_cancels):
                    await asyncio.sleep(0.02)
                    running.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await running.task
    await asyncio.sleep(0)

    assert running.task.cancelled()
    assert running.status.events == [
        McpServerStatusChanged(McpServerState.LISTENING, port=port),
        McpServerStatusChanged(McpServerState.STOPPED),
    ]
    assert _running_tasks_besides_sse_watcher() == set()
    bind_mcp_listener(port).close()


async def test_a_failure_mid_run_is_logged_at_once_and_leaves_nothing_running(
    monkeypatch, caplog
):
    fail = asyncio.Event()

    async def failing_main_loop(self) -> None:
        await fail.wait()
        raise RuntimeError("simulated uvicorn failure")

    monkeypatch.setattr(uvicorn.Server, "main_loop", failing_main_loop)
    bus = EventBus()
    status = ServerStatusLog(bus)
    listener = bind_mcp_listener(0)
    port = listener.getsockname()[1]
    server = McpModeServer(
        listener=listener,
        token=TOKEN,
        settings=_SETTINGS,
        voice_guide=FakeVoiceGuide(),
        bus=bus,
    )
    task = server.start()
    await asyncio.wait_for(status.listening.wait(), 5)

    fail.set()
    await _until(lambda: len(status.events) == 2)
    logged_by_then = [
        record
        for record in caplog.records
        if record.name == _SERVER_LOGGER and record.levelno == logging.ERROR
    ]
    with pytest.raises(RuntimeError, match="simulated uvicorn failure"):
        await task
    await asyncio.sleep(0)

    assert status.events[1] == McpServerStatusChanged(
        McpServerState.FAILED, reason="simulated uvicorn failure"
    )
    assert len(logged_by_then) == 1
    assert _running_tasks_besides_sse_watcher() == set()
    bind_mcp_listener(port).close()


async def test_a_stop_nobody_asked_for_is_logged_as_a_warning(monkeypatch, caplog):
    async def returning_main_loop(self) -> None:
        return None

    monkeypatch.setattr(uvicorn.Server, "main_loop", returning_main_loop)
    bus = EventBus()
    status = ServerStatusLog(bus)
    listener = bind_mcp_listener(0)
    server = McpModeServer(
        listener=listener,
        token=TOKEN,
        settings=_SETTINGS,
        voice_guide=FakeVoiceGuide(),
        bus=bus,
    )

    await asyncio.wait_for(server.start(), 5)

    assert [event.state for event in status.events] == [
        McpServerState.LISTENING,
        McpServerState.STOPPED,
    ]
    warnings = [
        record
        for record in caplog.records
        if record.name == _SERVER_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1


async def test_the_server_task_is_named_mcp_server():
    listener = bind_mcp_listener(0)
    task = _build_server(listener).start()

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert task.get_name() == "mcp-server"


@pytest.mark.parametrize("failure_lands", ["after_the_cancel", "with_the_cancel"])
async def test_a_failure_during_a_requested_stop_still_shuts_uvicorn_down(
    monkeypatch, caplog, failure_lands
):
    fail = asyncio.Event()

    async def main_loop_failing_on_demand(self) -> None:
        await fail.wait()
        raise RuntimeError("simulated uvicorn failure")

    monkeypatch.setattr(uvicorn.Server, "main_loop", main_loop_failing_on_demand)
    bus = EventBus()
    status = ServerStatusLog(bus)
    listener = bind_mcp_listener(0)
    port = listener.getsockname()[1]
    server = McpModeServer(
        listener=listener,
        token=TOKEN,
        settings=_SETTINGS,
        voice_guide=FakeVoiceGuide(),
        bus=bus,
    )
    task = server.start()
    await asyncio.wait_for(status.listening.wait(), 5)

    task.cancel()
    if failure_lands == "after_the_cancel":
        await asyncio.sleep(0.05)
    fail.set()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    await asyncio.sleep(0)
    gc.collect()

    assert task.cancelled()
    assert [event.state for event in status.events] == [
        McpServerState.LISTENING,
        McpServerState.FAILED,
    ]
    assert _running_tasks_besides_sse_watcher() == set()
    assert not any("never retrieved" in message for message in caplog.messages)
    bind_mcp_listener(port).close()


async def test_a_session_that_cannot_be_terminated_does_not_block_the_stop(
    monkeypatch,
):
    async def failing_terminate(self) -> None:
        raise RuntimeError("simulated terminate failure")

    monkeypatch.setattr(StreamableHTTPServerTransport, "terminate", failing_terminate)

    async with _serving(FakeVoiceGuide()) as running:
        port = running.server.port
        with contextlib.suppress(Exception):
            async with _client(running.url, terminate_on_close=False):
                await asyncio.wait_for(running.stop(), 5)
    await asyncio.sleep(0)

    assert running.task.cancelled()
    assert running.status.events[-1] == McpServerStatusChanged(McpServerState.STOPPED)
    assert _running_tasks_besides_sse_watcher() == set()
    bind_mcp_listener(port).close()
