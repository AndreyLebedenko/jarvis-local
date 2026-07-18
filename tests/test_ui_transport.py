import asyncio
from pathlib import Path

import aiohttp
import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    DataBoundary,
    PiperTtsSettings,
    SileroTtsSettings,
    VadSettings,
)
from jarvis.core.lifecycle import ModelRequestInput, ModelRequestStarted
from jarvis.dialog.thinking_mode import ReasoningLevel, ReasoningLevelChanged
from jarvis.journal import (
    JournalEvent,
    JournalEventAppended,
    JournalRecorder,
    JournalSearchIndex,
    JournalStore,
)
from jarvis.tools.interception import ToolCallStarted
from jarvis.ui.contract import (
    EventLevel,
    HealthStatus,
    ModelRequestItem,
    ModelRequestSummary,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)
from jarvis.ui.transport import (
    PROTOCOL_VERSION,
    ProtocolError,
    UiStateStore,
    UiTransportServer,
    _Client,
    hello_message,
    make_message,
    parse_message,
    serialize_message,
    token_matches,
)
from jarvis.ui.visibility import VisibilityModeChanged


class _FakeControlApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def toggle_thinking(self) -> None:
        self.calls.append(("toggle_thinking", None))

    def set_reasoning_level(self, level_value: str) -> None:
        self.calls.append(("set_reasoning_level", level_value))

    def set_mcp_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_mcp_enabled", str(enabled)))

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

    def save_config_selection(
        self,
        model: str,
        microphone_device: str,
        *,
        ui_language=None,
        vad=None,
        tts_routes=None,
    ) -> None:
        self.calls.append(("save_config_selection", f"{model}|{microphone_device}"))
        self.config_kwargs = {
            "ui_language": ui_language,
            "vad": vad,
            "tts_routes": tts_routes,
        }


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


def test_data_source_axis_is_independent_from_visibility_and_inference_locality():
    state = UiStateStore()

    state.record_tool_boundary(DataBoundary.INTERNET)
    state.set_visibility_mode(VisibilityMode.HIDDEN)

    snapshot = state.snapshot()
    assert snapshot["data_source"] == {"source": "internet"}
    assert snapshot["data_locality"] == {"locality": "local"}
    assert snapshot["visibility"] == {"mode": "hidden"}


def test_mcp_off_state_clears_tools_and_reports_authoritative_status():
    state = UiStateStore()
    state.set_mcp_state(
        {
            "status": "on",
            "enabled": True,
            "tools": [
                {
                    "name": "web_search",
                    "provider": "search",
                    "enabled": True,
                    "available": True,
                }
            ],
        }
    )

    state.set_mcp_state({"status": "off", "enabled": False, "tools": []})

    assert state.snapshot()["mcp"] == {
        "status": "off",
        "enabled": False,
        "tools": [],
    }


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


def test_last_model_request_delta_contains_metadata_only():
    state = UiStateStore()

    delta = state.set_last_model_request(
        ModelRequestSummary(
            timestamp=123.0,
            items=(
                ModelRequestItem(ModelRequestInput.AUDIO, audio_duration_seconds=4.25),
                ModelRequestItem(ModelRequestInput.SCREENSHOT),
            ),
        )
    )

    assert delta is not None
    assert delta["payload"] == {
        "key": "last_model_request",
        "value": {
            "timestamp": 123.0,
            "items": [
                {"kind": "audio", "duration_seconds": 4.25},
                {"kind": "screenshot"},
            ],
        },
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
    server._dispatch_control("set_reasoning_level", {"level": "medium"})
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
        ("set_reasoning_level", "medium"),
        ("reset_context", None),
        ("reset_module", "vision"),
        ("set_visibility_mode", "hidden"),
        ("request_shutdown", None),
        ("request_model_options", None),
        ("request_microphone_options", None),
        ("save_config_selection", "demo|mic-1"),
    ]


@pytest.mark.parametrize("bad_arguments", [{}, {"level": 3}, {"level": None}])
def test_set_reasoning_level_rejects_missing_or_non_string_level(bad_arguments):
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    with pytest.raises(ProtocolError, match="set_reasoning_level"):
        server._dispatch_control("set_reasoning_level", bad_arguments)

    assert control_api.calls == []


def test_set_reasoning_level_rejects_an_unknown_level_value():
    """story-v1.3.1 task 3 item 11: unknown is rejected the same way as
    missing/non-string - a ProtocolError, not a silent no-op - so a
    misbehaving client sees its command actually failed."""
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    with pytest.raises(ProtocolError, match="unknown reasoning level"):
        server._dispatch_control("set_reasoning_level", {"level": "max"})

    assert control_api.calls == []


def test_reset_module_rejects_an_unknown_module_id():
    """task-v1.5.1-2: with StatusConsoleApi's silent warn-and-return guard
    removed, the transport owns membership validation - a WS client with a
    bad module id gets a ProtocolError, and the control API is never
    reached (it would raise ValueError)."""
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    with pytest.raises(ProtocolError, match="unknown module id"):
        server._dispatch_control("reset_module", {"module_id": "not-a-module"})

    assert control_api.calls == []


def test_set_visibility_mode_rejects_an_unknown_mode():
    """task-v1.5.1-2: same transport-owned membership validation as
    reset_module, for the visibility axis."""
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    with pytest.raises(ProtocolError, match="unknown visibility mode"):
        server._dispatch_control("set_visibility_mode", {"mode": "invisible"})

    assert control_api.calls == []


@pytest.mark.asyncio
async def test_reasoning_level_changed_projects_level_and_derived_is_enabled():
    """story-v1.3.1 task 3: the transport payload carries the authoritative
    graded level, plus is_enabled as a derived protocol-v1 compatibility
    field (false only for off)."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()

    await bus.publish(
        ReasoningLevelChanged,
        ReasoningLevelChanged(level=ReasoningLevel.OFF, source="HOTKEY"),
    )
    assert server.state.snapshot()["thinking"] == {
        "level": "off",
        "is_enabled": False,
    }

    await bus.publish(
        ReasoningLevelChanged,
        ReasoningLevelChanged(level=ReasoningLevel.MEDIUM, source="UI"),
    )
    assert server.state.snapshot()["thinking"] == {
        "level": "medium",
        "is_enabled": True,
    }


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
async def test_server_projects_turn_data_source_from_real_tool_start_only():
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        await bus.publish(
            ModelRequestStarted,
            ModelRequestStarted(
                timestamp=1.0,
                inputs=(ModelRequestInput.CLIPBOARD,),
                audio_duration_seconds=None,
            ),
        )
        assert server.state.snapshot()["data_source"] == {"source": "local_only"}

        await bus.publish(
            ToolCallStarted,
            ToolCallStarted(
                correlation_id="call-1",
                tool_name="web_search",
                provider="search",
                arguments={"query": "weather"},
                outbound_summary="search.web_search(query='weather')",
                timestamp=2.0,
                data_boundary=DataBoundary.INTERNET,
            ),
        )
        assert server.state.snapshot()["data_source"] == {"source": "internet"}
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)


def test_turn_data_source_keeps_the_widest_declared_boundary():
    state = UiStateStore()

    state.record_tool_boundary(DataBoundary.LOCAL)
    assert state.snapshot()["data_source"] == {"source": "local_only"}
    state.record_tool_boundary(DataBoundary.UNKNOWN)
    assert state.snapshot()["data_source"] == {"source": "unknown"}
    state.record_tool_boundary(DataBoundary.LAN)
    assert state.snapshot()["data_source"] == {"source": "lan"}
    state.record_tool_boundary(DataBoundary.UNKNOWN)
    assert state.snapshot()["data_source"] == {"source": "lan"}
    state.record_tool_boundary(DataBoundary.INTERNET)
    state.record_tool_boundary(DataBoundary.LAN)

    assert state.snapshot()["data_source"] == {"source": "internet"}


def test_set_mcp_enabled_control_requires_boolean_target():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("set_mcp_enabled", {"enabled": True})

    assert control_api.calls == [("set_mcp_enabled", "True")]
    with pytest.raises(ProtocolError, match="arguments.enabled"):
        server._dispatch_control("set_mcp_enabled", {"enabled": "true"})


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


# --- story-v1.3.0-task-2: configuration iteration 2 command arguments -------


def _full_config_arguments() -> dict:
    return {
        "model": "demo",
        "microphone": "mic-1",
        "ui_language": "ru",
        "vad": {
            "threshold": 0.6,
            "max_chunk_seconds": 25,
            "request_end_pause_seconds": 1.5,
            "resume_cooldown_seconds": 0.5,
        },
        "tts_routes": {
            "ru": {
                "engine": "silero",
                "model": "custom_ru",
                "language": "ru",
                "speaker": "eugene",
                "sample_rate": 24000,
                "put_accent": True,
                "put_yo": None,
            },
            "en": {
                "engine": "piper",
                "model": "voices/en.onnx",
                "config_path": None,
                "use_cuda": False,
                "espeak_data_dir": None,
                "download_dir": None,
                "speaker_id": 2,
                "length_scale": 1.2,
                "noise_scale": None,
                "noise_w_scale": None,
                "normalize_audio": False,
                "volume": 0.9,
            },
        },
    }


def test_save_config_selection_parses_iteration_2_arguments():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("save_config_selection", _full_config_arguments())

    assert control_api.config_kwargs["ui_language"] == "ru"
    assert control_api.config_kwargs["vad"] == VadSettings(
        threshold=0.6,
        max_chunk_seconds=25,
        request_end_pause_seconds=1.5,
        resume_cooldown_seconds=0.5,
    )
    assert control_api.config_kwargs["tts_routes"] == {
        "ru": SileroTtsSettings(
            model="custom_ru",
            language="ru",
            speaker="eugene",
            sample_rate=24000,
            put_accent=True,
        ),
        "en": PiperTtsSettings(
            model="voices/en.onnx",
            speaker_id=2,
            length_scale=1.2,
            normalize_audio=False,
            volume=0.9,
        ),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("speaker_id", 1.5), ("use_cuda", "yes"), ("volume", True)],
)
def test_typed_tts_route_rejects_wrong_engine_parameter_types(field, value):
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)
    arguments = _full_config_arguments()
    arguments["tts_routes"]["en"][field] = value

    with pytest.raises(ProtocolError, match=field):
        server._dispatch_control("save_config_selection", arguments)

    assert control_api.calls == []


def test_typed_tts_route_rejects_fields_from_the_other_engine():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)
    arguments = _full_config_arguments()
    arguments["tts_routes"]["en"]["speaker"] = "wrong variant"

    with pytest.raises(ProtocolError, match="requires exactly"):
        server._dispatch_control("save_config_selection", arguments)

    assert control_api.calls == []


def test_save_config_selection_without_new_fields_passes_none():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control(
        "save_config_selection", {"model": "demo", "microphone": "mic-1"}
    )

    assert control_api.config_kwargs == {
        "ui_language": None,
        "vad": None,
        "tts_routes": None,
    }


@pytest.mark.parametrize(
    "corruption",
    [
        {"ui_language": 5},
        {"vad": "loud"},
        {"vad": {"threshold": 0.5}},
        {
            "vad": {
                "threshold": True,
                "max_chunk_seconds": 25,
                "request_end_pause_seconds": 1.5,
                "resume_cooldown_seconds": 0.5,
            }
        },
        {
            "vad": {
                "threshold": 0.5,
                "max_chunk_seconds": 25.5,
                "request_end_pause_seconds": 1.5,
                "resume_cooldown_seconds": 0.5,
            }
        },
        {"tts_routes": ["ru"]},
        {"tts_routes": {"ru": "silero"}},
        {"tts_routes": {"ru": {"engine": "silero"}}},
    ],
)
def test_malformed_iteration_2_arguments_raise_protocol_error(corruption):
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)
    arguments = {"model": "demo", "microphone": "mic-1", **corruption}

    with pytest.raises(ProtocolError):
        server._dispatch_control("save_config_selection", arguments)

    assert control_api.calls == []


def test_snapshot_contains_config_values_section():
    store = UiStateStore()

    snapshot = store.snapshot()

    values = snapshot["config_values"]
    assert values["ui_language"] == "en"
    assert values["vad"]["threshold"] == 0.5
    assert values["tts"]["routes"]["ru"] == {
        "engine": "silero",
        "model": "v3_1_ru",
        "language": "ru",
        "speaker": "baya",
        "sample_rate": 48000,
        "put_accent": None,
        "put_yo": None,
    }
    assert [field["name"] for field in values["tts"]["schemas"]["silero"]] == [
        "model",
        "language",
        "speaker",
        "sample_rate",
        "put_accent",
        "put_yo",
    ]
    assert values["vad_ranges"]["max_chunk_seconds"] == [1, 120]


# --- story-v1.5.0 journal transport API ------------------------------------


@pytest.mark.asyncio
async def test_journal_sessions_feed_and_search_use_existing_http_transport(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    store = JournalStore(tmp_path)
    search_index = JournalSearchIndex(store, tmp_path)
    session_id = "20260716-153000-ab12"
    later_session_id = "20260717-090000-cd34"
    store.append(
        _journal_event(
            session_id=session_id,
            timestamp="2026-07-16T15:30:00+01:00",
            source="voice",
            role="user",
            text="",
            media=("utterance.wav",),
        )
    )
    store.append(
        _journal_event(
            session_id=session_id,
            timestamp="2026-07-16T15:30:02+01:00",
            source="assistant",
            role="assistant",
            text="The orbital relay is stable.",
        )
    )
    store.append(
        _journal_event(
            session_id=session_id,
            timestamp="2026-07-16T15:30:03+01:00",
            source="text",
            role="user",
            text="the real topic after voice",
        )
    )
    store.append(
        _journal_event(
            session_id=later_session_id,
            timestamp="2026-07-17T09:00:00+01:00",
            source="text",
            role="user",
            text="reactor check",
        )
    )
    store.append(
        _journal_event(
            session_id=later_session_id,
            timestamp="2026-07-17T09:00:01+01:00",
            source="assistant",
            role="assistant",
            text="The reactor telemetry is nominal.",
        )
    )
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_search_index=search_index,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            sessions = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/sessions?token=valid-token",
            )
            assert sessions["status"] == "ok"
            assert sessions["sessions"] == [
                {
                    "id": session_id,
                    "start_timestamp": "2026-07-16T15:30:00+01:00",
                    "end_timestamp": "2026-07-16T15:30:03+01:00",
                    "title": "the real topic after voice",
                },
                {
                    "id": later_session_id,
                    "start_timestamp": "2026-07-17T09:00:00+01:00",
                    "end_timestamp": "2026-07-17T09:00:01+01:00",
                    "title": "reactor check",
                },
            ]

            feed = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/sessions/{session_id}"
                "?token=valid-token",
            )
            assert feed["session_id"] == session_id
            assert feed["events"][0]["transcript"] is None
            assert feed["events"][0]["media"] == [
                {
                    "path": "utterance.wav",
                    "url": (
                        f"/api/journal/media/{session_id}/utterance.wav"
                        "?token=valid-token"
                    ),
                }
            ]
            assert feed["events"][1]["text"] == "The orbital relay is stable."

            search = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/search"
                "?token=valid-token&query=reactor&date_from=2026-07-17"
                "&date_to=2026-07-17",
            )
            assert [
                (hit["session_id"], hit["event_position"], hit["snippet"])
                for hit in search["hits"]
            ] == [(later_session_id, 1, "The [reactor] telemetry is nominal.")]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_media_serves_known_types_and_rejects_traversal(
    tmp_path: Path,
) -> None:
    session_id = "20260716-153000-ab12"
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "clip.wav").write_bytes(b"RIFF demo")
    (session_dir / "screen.png").write_bytes(b"\x89PNG demo")
    (session_dir / "photo.jpg").write_bytes(b"\xff\xd8 demo")
    (tmp_path / "outside.wav").write_bytes(b"outside")
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_store=JournalStore(tmp_path),
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            for name, content_type in [
                ("clip.wav", "audio/wav"),
                ("screen.png", "image/png"),
                ("photo.jpg", "image/jpeg"),
            ]:
                response = await session.get(
                    f"http://127.0.0.1:{info.port}/api/journal/media/"
                    f"{session_id}/{name}?token=valid-token"
                )
                assert response.status == 200
                assert response.headers["Content-Type"].startswith(content_type)
                await response.read()

            traversal = await session.get(
                f"http://127.0.0.1:{info.port}/api/journal/media/"
                f"{session_id}/%2e%2e/outside.wav?token=valid-token"
            )
            assert traversal.status == 404
            assert await traversal.read() != b"outside"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_hidden_mode_blocks_http_and_suppresses_pushes(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    store = JournalStore(tmp_path)
    event = _journal_event(
        session_id="20260716-153000-ab12",
        timestamp="2026-07-16T15:30:00+01:00",
        source="assistant",
        role="assistant",
        text="hidden text",
    )
    store.append(event)
    media_dir = tmp_path / event.session_id
    media_dir.mkdir(exist_ok=True)
    (media_dir / "clip.wav").write_bytes(b"RIFF demo")
    state = UiStateStore(visibility_mode=VisibilityMode.HIDDEN)
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        state=state,
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_search_index=JournalSearchIndex(store, tmp_path),
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            assert (
                await _get_json(
                    session,
                    f"http://127.0.0.1:{info.port}/api/journal/sessions"
                    "?token=valid-token",
                )
            ) == {"status": "hidden"}
            assert (
                await _get_json(
                    session,
                    f"http://127.0.0.1:{info.port}/api/journal/search"
                    "?token=valid-token&query=hidden",
                )
            ) == {"status": "hidden"}
            assert (
                await _get_json(
                    session,
                    f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                    f"{event.session_id}?token=valid-token",
                )
            ) == {"status": "hidden"}
            assert (
                await _get_json(
                    session,
                    f"http://127.0.0.1:{info.port}/api/journal/media/"
                    f"{event.session_id}/clip.wav?token=valid-token",
                )
            ) == {"status": "hidden"}

            async with session.ws_connect(info.websocket_url) as websocket:
                await websocket.send_json(hello_message("status-console", ["state"]))
                await websocket.receive_json()
                await websocket.receive_json()

                await bus.publish(JournalEventAppended, JournalEventAppended(event))
                with pytest.raises(TimeoutError):
                    await websocket.receive(timeout=0.05)

            await bus.publish(
                VisibilityModeChanged, VisibilityModeChanged(VisibilityMode.OPEN)
            )
            restored_feed = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                f"{event.session_id}?token=valid-token",
            )
            assert restored_feed["events"][0]["text"] == "hidden text"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_append_pushes_exactly_one_live_event(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    store = JournalStore(tmp_path)
    recorder = JournalRecorder(store, bus=bus, clock=_journal_clock())
    search_index = JournalSearchIndex(store, tmp_path)
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_search_index=search_index,
    )
    info = await server.start()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.ws_connect(info.websocket_url) as websocket,
        ):
            await websocket.send_json(hello_message("status-console", ["state"]))
            await websocket.receive_json()
            await websocket.receive_json()

            await recorder.record_assistant("live answer")
            await recorder.wait_for_pending()

            delta = await websocket.receive_json()
            assert delta["type"] == "delta"
            assert delta["payload"]["key"] == "journal_event"
            assert delta["payload"]["value"]["text"] == "live answer"
            assert delta["payload"]["value"]["transcript"] is None
            search = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/search"
                "?token=valid-token&query=live",
            )
            assert [
                (hit["session_id"], hit["event_position"], hit["snippet"])
                for hit in search["hits"]
            ] == [(delta["payload"]["value"]["session_id"], 0, "[live] answer")]
            with pytest.raises(TimeoutError):
                await websocket.receive(timeout=0.05)
    finally:
        await server.stop()


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict:
    response = await session.get(url)
    assert response.status == 200
    return await response.json()


def _journal_event(
    *,
    session_id: str,
    timestamp: str,
    source: str,
    role: str,
    text: str,
    media: tuple[str, ...] = (),
) -> JournalEvent:
    return JournalEvent(
        session_id=session_id,
        timestamp=timestamp,
        source=source,
        role=role,
        text=text,
        media=media,
        transcript=None,
    )


def _journal_clock():
    from datetime import UTC, datetime

    return lambda: datetime(2026, 7, 16, 15, 30, 0, tzinfo=UTC)
