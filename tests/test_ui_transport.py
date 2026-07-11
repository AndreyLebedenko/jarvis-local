import asyncio

import aiohttp
import pytest

from jarvis.core.bus import EventBus
from jarvis.ui.contract import (
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
)
from jarvis.ui.transport import (
    PROTOCOL_VERSION,
    UiStateStore,
    UiTransportServer,
    _Client,
    hello_message,
    make_message,
    parse_message,
    serialize_message,
    token_matches,
)


class _FakeControlApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def toggle_thinking(self) -> None:
        self.calls.append(("toggle_thinking", None))

    def reset_context(self) -> None:
        self.calls.append(("reset_context", None))

    def reset_module(self, module_id: str) -> None:
        self.calls.append(("reset_module", module_id))

    def set_visibility_mode(self, mode_value: str) -> None:
        self.calls.append(("set_visibility_mode", mode_value))

    def request_shutdown(self) -> None:
        self.calls.append(("request_shutdown", None))

    def request_model_options(self) -> None:
        self.calls.append(("request_model_options", None))

    def request_microphone_options(self) -> None:
        self.calls.append(("request_microphone_options", None))

    def save_config_selection(self, model: str, microphone_device: str) -> None:
        self.calls.append(("save_config_selection", f"{model}|{microphone_device}"))


def test_protocol_message_round_trips_with_channel_and_payload():
    message = make_message(
        "state", "delta", {"key": "model", "value": {"label": "demo"}}
    )

    parsed = parse_message(serialize_message(message))

    assert parsed.channel == "state"
    assert parsed.message_type == "delta"
    assert parsed.payload == {"key": "model", "value": {"label": "demo"}}


def test_protocol_rejects_unknown_version_and_non_object_payload():
    with pytest.raises(ValueError, match="unsupported protocol"):
        parse_message('{"protocol":2,"channel":"state","type":"snapshot","payload":{}}')
    with pytest.raises(ValueError, match="payload must be an object"):
        parse_message('{"protocol":1,"channel":"state","type":"snapshot","payload":[]}')


def test_token_check_is_exact_and_rejects_missing_or_similar_values():
    assert token_matches("secret", "secret")
    assert not token_matches("secret", None)
    assert not token_matches("secret", "Secret")
    assert not token_matches("secret", "secret-extra")


def test_hello_message_declares_identity_and_capabilities():
    message = hello_message("status-console", ["state", "control"])

    assert message == {
        "protocol": PROTOCOL_VERSION,
        "channel": "control",
        "type": "hello",
        "payload": {
            "client_id": "status-console",
            "capabilities": ["state", "control"],
        },
    }


def test_state_store_replaces_values_and_keeps_system_event_snapshot_history():
    state = UiStateStore(model_label="demo")

    delta = state.set_runtime_state(RuntimeState.THINKING, "working")
    event = SystemEvent(1.0, "ENGINE", EventLevel.INFO, "ready")
    event_delta = state.add_system_event(event)

    assert delta is not None
    assert delta["payload"] == {
        "key": "runtime",
        "value": {
            "state": "thinking",
            "label": "Thinking",
            "substatus": "working",
        },
    }
    assert event_delta["payload"] == {
        "key": "system_event",
        "value": {
            "timestamp": 1.0,
            "source": "ENGINE",
            "level": "info",
            "message": "ready",
            "correlation_id": None,
        },
    }
    assert state.snapshot()["system_events"] == [
        {
            "timestamp": 1.0,
            "source": "ENGINE",
            "level": "info",
            "message": "ready",
            "correlation_id": None,
        }
    ]


def test_module_delta_keeps_the_value_present_when_it_was_enqueued():
    state = UiStateStore()

    first_delta = state.set_module_health(
        ModuleHealth(ModuleId.MICROPHONE, HealthStatus.UNAVAILABLE, "sleeping")
    )
    state.set_module_health(
        ModuleHealth(ModuleId.MICROPHONE, HealthStatus.OK, "listening")
    )

    assert first_delta is not None
    assert first_delta["payload"]["value"] == {
        "microphone": {
            "module": "microphone",
            "status": "unavailable",
            "detail": "sleeping",
        }
    }


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_full_client_queue_drops_and_closes_the_client():
    server = UiTransportServer(EventBus(), _FakeControlApi())
    client = _Client(
        websocket=_FakeWebSocket(),
        queue=asyncio.Queue(maxsize=1),
        writer_task=None,
        client_id="stalled-client",
    )
    client.queue.put_nowait("already-full")
    server._clients.add(client)

    server._publish_delta(
        make_message("state", "delta", {"key": "runtime", "value": {}})
    )
    await asyncio.sleep(0)

    assert client not in server._clients
    assert client.websocket.closed


def test_server_dispatches_all_existing_status_console_control_paths():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("toggle_thinking", {})
    server._dispatch_control("reset_context", {})
    server._dispatch_control("reset_module", {"module_id": "vision"})
    server._dispatch_control("set_visibility_mode", {"mode": "hidden"})
    server._dispatch_control("request_shutdown", {})
    server._dispatch_control("request_model_options", {})
    server._dispatch_control("request_microphone_options", {})
    server._dispatch_control(
        "save_config_selection", {"model": "demo", "microphone": "mic-1"}
    )

    assert control_api.calls == [
        ("toggle_thinking", None),
        ("reset_context", None),
        ("reset_module", "vision"),
        ("set_visibility_mode", "hidden"),
        ("request_shutdown", None),
        ("request_model_options", None),
        ("request_microphone_options", None),
        ("save_config_selection", "demo|mic-1"),
    ]


@pytest.mark.asyncio
async def test_server_rejects_connection_without_valid_token():
    server = UiTransportServer(
        EventBus(), _FakeControlApi(), token_factory=lambda: "valid-token"
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientResponseError) as error:
                await session.ws_connect(f"ws://127.0.0.1:{info.port}/ws")
            assert error.value.status == 401
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_requires_hello_before_state_or_control_traffic():
    server = UiTransportServer(
        EventBus(), _FakeControlApi(), token_factory=lambda: "valid-token"
    )
    info = await server.start()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.ws_connect(info.websocket_url) as websocket,
        ):
            await websocket.send_json(
                make_message("control", "command", {"command": "reset_context"})
            )
            error = await websocket.receive_json()
            assert error["type"] == "error"
            assert error["payload"]["code"] == "invalid_hello"
            assert (await websocket.receive()).type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
            }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_runs_handshake_snapshot_delta_and_control_cycle():
    bus = EventBus()
    control_api = _FakeControlApi()
    server = UiTransportServer(
        bus,
        control_api,
        state=UiStateStore(model_label="demo-model"),
        token_factory=lambda: "valid-token",
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.get(info.url)
            assert response.status == 200
            await response.read()

            async with session.ws_connect(info.websocket_url) as websocket:
                await websocket.send_json(
                    hello_message("status-console", ["state", "control"])
                )

                hello_ack = await websocket.receive_json()
                snapshot = await websocket.receive_json()
                assert hello_ack["type"] == "hello_ack"
                assert hello_ack["payload"]["client_id"] == "status-console"
                assert snapshot["type"] == "snapshot"
                assert snapshot["payload"]["model"] == {"label": "demo-model"}

                await bus.publish(
                    SystemEvent,
                    SystemEvent(2.0, "ENGINE", EventLevel.INFO, "transport ready"),
                )
                delta = await websocket.receive_json()
                assert delta["type"] == "delta"
                assert delta["payload"]["key"] == "system_event"

                await websocket.send_json(
                    make_message(
                        "control",
                        "command",
                        {
                            "command": "set_visibility_mode",
                            "arguments": {"mode": "hidden"},
                        },
                    )
                )
                acknowledgement = await websocket.receive_json()
                assert acknowledgement["type"] == "command_ack"
                assert control_api.calls == [("set_visibility_mode", "hidden")]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_stop_closes_connected_clients_and_unsubscribes_bus_handlers():
    bus = EventBus()
    server = UiTransportServer(
        bus, _FakeControlApi(), token_factory=lambda: "valid-token"
    )
    info = await server.start()
    session = aiohttp.ClientSession()
    websocket = await session.ws_connect(info.websocket_url)
    await websocket.send_json(hello_message("status-console", ["state"]))
    await websocket.receive_json()
    await websocket.receive_json()

    await server.stop()
    await websocket.receive()
    assert websocket.closed
    assert server.token == "valid-token"
    restarted_info = await server.start()
    assert restarted_info.token == "valid-token"
    await server.stop()
    await session.close()
    await bus.publish(
        SystemEvent, SystemEvent(3.0, "ENGINE", EventLevel.INFO, "ignored")
    )
    await asyncio.sleep(0)
