"""Local HTTP+WebSocket transport for Jarvis UI surfaces."""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from aiohttp import web

from jarvis.audio.input import MicSleepToggled
from jarvis.core.bus import EventBus
from jarvis.dialog.thinking_mode import ThinkingModeToggled
from jarvis.ui.contract import (
    DataLocality,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)
from jarvis.ui.status_console import (
    MicrophoneOptionsAvailable,
    ModelOptionsAvailable,
    StatusConsoleApi,
    UiConfigSaved,
    data_locality_payload,
    module_health_payload,
    runtime_state_payload,
    system_event_payload,
    thinking_mode_payload,
    visibility_mode_payload,
)
from jarvis.ui.text import DEFAULT_UI_LANGUAGE, ui_text
from jarvis.ui.visibility import VisibilityModeChanged

PROTOCOL_VERSION = 1
MAX_SYSTEM_EVENTS = 200
HANDSHAKE_TIMEOUT_SECONDS = 5.0
UI_DIR = Path(__file__).resolve().parent / "status_console_ui"

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JsonObject = dict[str, JSONValue]


class ProtocolError(ValueError):
    """Raised when a message does not satisfy protocol v1."""


@dataclass(frozen=True)
class ProtocolMessage:
    channel: str
    message_type: str
    payload: JsonObject


def make_message(
    channel: str, message_type: str, payload: Mapping[str, JSONValue]
) -> JsonObject:
    if channel not in {"state", "control"}:
        raise ProtocolError(f"unsupported channel: {channel}")
    return {
        "protocol": PROTOCOL_VERSION,
        "channel": channel,
        "type": message_type,
        "payload": dict(payload),
    }


def serialize_message(message: JsonObject) -> str:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def parse_message(raw: str) -> ProtocolMessage:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProtocolError("message is not valid JSON") from error
    if not isinstance(decoded, dict):
        raise ProtocolError("message must be a JSON object")
    if decoded.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    channel = decoded.get("channel")
    message_type = decoded.get("type")
    payload = decoded.get("payload")
    if not isinstance(channel, str) or channel not in {"state", "control"}:
        raise ProtocolError("message channel is invalid")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("message type is invalid")
    if not isinstance(payload, dict):
        raise ProtocolError("message payload must be an object")
    return ProtocolMessage(
        channel=channel,
        message_type=message_type,
        payload=cast(JsonObject, payload),
    )


def token_matches(expected: str, actual: str | None) -> bool:
    if actual is None:
        return False
    return hmac.compare_digest(
        hashlib.sha256(expected.encode("utf-8")).digest(),
        hashlib.sha256(actual.encode("utf-8")).digest(),
    )


def hello_message(client_id: str, capabilities: Sequence[str]) -> JsonObject:
    return make_message(
        "control",
        "hello",
        {
            "client_id": client_id,
            "capabilities": list(capabilities),
        },
    )


class ControlApi(Protocol):
    def toggle_thinking(self) -> None: ...

    def reset_context(self) -> None: ...

    def reset_module(self, module_id: str) -> None: ...

    def set_visibility_mode(self, mode_value: str) -> None: ...

    def request_shutdown(self) -> None: ...

    def request_model_options(self) -> None: ...

    def request_microphone_options(self) -> None: ...

    def save_config_selection(self, model: str, microphone_device: str) -> None: ...


class UiStateStore:
    """Owns the JSON state projection shared by all UI clients."""

    def __init__(
        self,
        *,
        model_label: str = "",
        runtime_state: RuntimeState = RuntimeState.IDLE,
        data_locality: DataLocality = DataLocality.LOCAL,
        thinking_enabled: bool = False,
        visibility_mode: VisibilityMode = VisibilityMode.OPEN,
        language: str = DEFAULT_UI_LANGUAGE,
    ) -> None:
        self._language = language
        self._state: JsonObject = {
            "runtime": cast(
                JsonObject, runtime_state_payload(runtime_state, language=language)
            ),
            "modules": {},
            "data_locality": cast(JsonObject, data_locality_payload(data_locality)),
            "model": {"label": model_label},
            "system_events": [],
            "thinking": cast(JsonObject, thinking_mode_payload(thinking_enabled)),
            "visibility": cast(JsonObject, visibility_mode_payload(visibility_mode)),
            "model_options": {"options": [], "current": model_label},
            "microphone_options": {"options": [], "current": ""},
            "pending_restart": {"pending": False},
            "ui_language": {"language": language},
        }

    @property
    def language(self) -> str:
        return self._language

    def snapshot(self) -> JsonObject:
        return json.loads(json.dumps(self._state, ensure_ascii=False))

    def snapshot_message(self) -> JsonObject:
        return make_message("state", "snapshot", self.snapshot())

    def _replace(self, key: str, value: JSONValue) -> JsonObject | None:
        if self._state[key] == value:
            return None
        self._state[key] = value
        return make_message("state", "delta", {"key": key, "value": value})

    def set_runtime_state(
        self, state: RuntimeState, substatus: str | None = None
    ) -> JsonObject | None:
        return self._replace(
            "runtime",
            cast(JsonObject, runtime_state_payload(state, substatus, self._language)),
        )

    def set_module_health(self, health: ModuleHealth) -> JsonObject | None:
        modules = cast(dict[str, JSONValue], self._state["modules"])
        value = cast(JsonObject, module_health_payload(health))
        if modules.get(health.module.value) == value:
            return None
        modules[health.module.value] = value
        return make_message(
            "state", "delta", {"key": "modules", "value": dict(modules)}
        )

    def set_data_locality(self, locality: DataLocality) -> JsonObject | None:
        return self._replace(
            "data_locality", cast(JsonObject, data_locality_payload(locality))
        )

    def set_model_label(self, label: str) -> JsonObject | None:
        return self._replace("model", {"label": label})

    def add_system_event(self, event: SystemEvent) -> JsonObject:
        events = cast(list[JSONValue], self._state["system_events"])
        payload = cast(JsonObject, system_event_payload(event))
        events.append(payload)
        del events[:-MAX_SYSTEM_EVENTS]
        return make_message(
            "state",
            "delta",
            {"key": "system_event", "value": payload},
        )

    def set_thinking_mode(self, is_enabled: bool) -> JsonObject | None:
        return self._replace(
            "thinking", cast(JsonObject, thinking_mode_payload(is_enabled))
        )

    def set_visibility_mode(self, mode: VisibilityMode) -> JsonObject | None:
        return self._replace(
            "visibility", cast(JsonObject, visibility_mode_payload(mode))
        )

    def set_model_options(self, options: list[str], current: str) -> JsonObject | None:
        return self._replace("model_options", {"options": options, "current": current})

    def set_microphone_options(
        self, options: list[str], current: str
    ) -> JsonObject | None:
        return self._replace(
            "microphone_options", {"options": options, "current": current}
        )

    def set_pending_restart(self, pending: bool) -> JsonObject | None:
        return self._replace("pending_restart", {"pending": pending})


@dataclass(frozen=True)
class UiTransportInfo:
    host: str
    port: int
    token: str

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?token={self.token}"

    @property
    def websocket_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws?token={self.token}"

    @property
    def touchstrip_url(self) -> str:
        return f"http://{self.host}:{self.port}/touchstrip.html?token={self.token}"


@dataclass(eq=False)
class _Client:
    websocket: web.WebSocketResponse
    queue: asyncio.Queue[str]
    writer_task: asyncio.Task[None] | None
    client_id: str
    is_closing: bool = False


class UiTransportServer:
    """Serves local UI files and projects bus events to WS clients."""

    def __init__(
        self,
        bus: EventBus,
        control_api: ControlApi | StatusConsoleApi,
        *,
        state: UiStateStore | None = None,
        logger: logging.Logger | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        token_factory: Callable[[], str] | None = None,
        ui_dir: Path = UI_DIR,
    ) -> None:
        self._bus = bus
        self._control_api = control_api
        self._state = state or UiStateStore()
        self._logger = logger or logging.getLogger(__name__)
        self._host = host
        self._port = port
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._ui_dir = ui_dir
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._token: str | None = None
        self._clients: set[_Client] = set()
        self._subscriptions: list[tuple[type[object], Callable[..., object]]] = []

    @property
    def state(self) -> UiStateStore:
        return self._state

    @property
    def token(self) -> str:
        if self._token is None:
            raise RuntimeError("server has not been started")
        return self._token

    async def start(self) -> UiTransportInfo:
        if self._runner is not None:
            raise RuntimeError("server is already started")
        if isinstance(self._control_api, StatusConsoleApi):
            self._control_api.set_loop(asyncio.get_running_loop())
        if self._token is None:
            self._token = self._token_factory()
        self._subscribe_to_bus()
        app = web.Application()
        app.router.add_get("/ws", self._websocket_handler)
        app.router.add_get("/", self._index_handler)
        app.router.add_static("/", self._ui_dir, show_index=False)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        sockets = self._site._server.sockets if self._site._server is not None else None
        if not sockets:
            await self.stop()
            raise RuntimeError("UI transport server did not expose a listening socket")
        port = int(sockets[0].getsockname()[1])
        return UiTransportInfo(host=self._host, port=port, token=self.token)

    async def _index_handler(self, request: web.Request) -> web.FileResponse:
        del request
        return web.FileResponse(self._ui_dir / "index.html")

    async def stop(self) -> None:
        if self._runner is None:
            return
        for event_type, handler in self._subscriptions:
            self._bus.unsubscribe(event_type, cast(Callable[..., object], handler))
        self._subscriptions.clear()
        clients = list(self._clients)
        self._clients.clear()
        for client in clients:
            await self._close_client(client)
        await self._runner.cleanup()
        self._runner = None
        self._site = None

    def set_runtime_state(
        self, state: RuntimeState, substatus: str | None = None
    ) -> None:
        self._publish_delta(self._state.set_runtime_state(state, substatus))

    def set_module_health(self, health: ModuleHealth) -> None:
        self._publish_delta(self._state.set_module_health(health))

    def set_data_locality(self, locality: DataLocality) -> None:
        self._publish_delta(self._state.set_data_locality(locality))

    def set_model_label(self, label: str) -> None:
        self._publish_delta(self._state.set_model_label(label))

    def set_thinking_mode(self, is_enabled: bool) -> None:
        self._publish_delta(self._state.set_thinking_mode(is_enabled))

    def set_visibility_mode(self, mode: VisibilityMode) -> None:
        self._publish_delta(self._state.set_visibility_mode(mode))

    def _subscribe_to_bus(self) -> None:
        subscriptions: list[tuple[type[object], Callable[..., object]]] = [
            (SystemEvent, self._on_system_event),
            (ThinkingModeToggled, self._on_thinking_mode_toggled),
            (VisibilityModeChanged, self._on_visibility_mode_changed),
            (MicSleepToggled, self._on_mic_sleep_toggled),
            (ModelOptionsAvailable, self._on_model_options_available),
            (MicrophoneOptionsAvailable, self._on_microphone_options_available),
            (UiConfigSaved, self._on_ui_config_saved),
        ]
        for event_type, handler in subscriptions:
            self._bus.subscribe(event_type, cast(Callable[..., object], handler))
        self._subscriptions = subscriptions

    async def _on_system_event(self, event: SystemEvent) -> None:
        # Runtime-state reaction to errors lives in RuntimeStateTracker;
        # this server only projects state it is told about.
        self._publish_delta(self._state.add_system_event(event))

    async def _on_thinking_mode_toggled(self, event: ThinkingModeToggled) -> None:
        self._publish_delta(self._state.set_thinking_mode(event.is_enabled))

    async def _on_visibility_mode_changed(self, event: VisibilityModeChanged) -> None:
        self._publish_delta(self._state.set_visibility_mode(event.mode))

    async def _on_mic_sleep_toggled(self, event: MicSleepToggled) -> None:
        health = ModuleHealth(
            module=ModuleId.MICROPHONE,
            status=HealthStatus.OK if event.is_awake else HealthStatus.UNAVAILABLE,
            detail=ui_text(
                "mic_detail_listening" if event.is_awake else "mic_detail_muted",
                self._state.language,
            ),
        )
        self._publish_delta(self._state.set_module_health(health))

    async def _on_model_options_available(self, event: ModelOptionsAvailable) -> None:
        self._publish_delta(self._state.set_model_options(event.options, event.current))

    async def _on_microphone_options_available(
        self, event: MicrophoneOptionsAvailable
    ) -> None:
        self._publish_delta(
            self._state.set_microphone_options(event.options, event.current)
        )

    async def _on_ui_config_saved(self, event: UiConfigSaved) -> None:
        del event
        self._publish_delta(self._state.set_pending_restart(True))

    def _publish_delta(self, message: JsonObject | None) -> None:
        if message is None:
            return
        serialized = serialize_message(message)
        for client in tuple(self._clients):
            self._enqueue_serialized(client, serialized)

    def _enqueue_message(self, client: _Client, message: JsonObject) -> None:
        self._enqueue_serialized(client, serialize_message(message))

    def _enqueue_serialized(self, client: _Client, serialized: str) -> None:
        if client.is_closing:
            return
        try:
            client.queue.put_nowait(serialized)
        except asyncio.QueueFull:
            client.is_closing = True
            self._clients.discard(client)
            self._logger.warning(
                "Dropping UI transport client with a full outbound queue: %s",
                client.client_id,
            )
            task = asyncio.create_task(self._close_client(client))
            task.add_done_callback(self._log_close_failure)

    def _log_close_failure(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._logger.error("UI transport client close failed", exc_info=exception)

    async def _close_client(self, client: _Client) -> None:
        client.is_closing = True
        self._clients.discard(client)
        if client.writer_task is not None:
            client.writer_task.cancel()
            await asyncio.gather(client.writer_task, return_exceptions=True)
        if not client.websocket.closed:
            await client.websocket.close()

    async def _websocket_handler(self, request: web.Request) -> web.StreamResponse:
        if not token_matches(self.token, request.query.get("token")):
            raise web.HTTPUnauthorized(text="invalid UI transport token")
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        try:
            first_message = await asyncio.wait_for(
                websocket.receive(), timeout=HANDSHAKE_TIMEOUT_SECONDS
            )
            if first_message.type is not web.WSMsgType.TEXT:
                await self._close_with_error(websocket, "handshake_required")
                return websocket
            try:
                hello = parse_message(first_message.data)
                client_id, capabilities = self._parse_hello(hello)
            except ProtocolError as error:
                await self._close_with_error(websocket, "invalid_hello", str(error))
                return websocket
            queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
            client = _Client(
                websocket,
                queue,
                asyncio.create_task(self._write_client_messages(websocket, queue)),
                client_id,
            )
            self._clients.add(client)
            try:
                self._enqueue_message(
                    client,
                    make_message(
                        "control",
                        "hello_ack",
                        {
                            "protocol": PROTOCOL_VERSION,
                            "client_id": client_id,
                            "capabilities": capabilities,
                        },
                    ),
                )
                self._enqueue_message(client, self._state.snapshot_message())
                async for message in websocket:
                    if message.type is web.WSMsgType.TEXT:
                        self._handle_client_message(client, message.data)
                    elif message.type is web.WSMsgType.ERROR:
                        self._logger.warning(
                            "UI WebSocket error: %s", websocket.exception()
                        )
            finally:
                await self._close_client(client)
        except TimeoutError:
            await self._close_with_error(websocket, "handshake_timeout")
        finally:
            if not websocket.closed:
                await websocket.close()
        return websocket

    @staticmethod
    def _parse_hello(message: ProtocolMessage) -> tuple[str, list[str]]:
        if message.channel != "control" or message.message_type != "hello":
            raise ProtocolError("first message must be control/hello")
        client_id = message.payload.get("client_id")
        capabilities = message.payload.get("capabilities")
        if not isinstance(client_id, str) or not client_id.strip():
            raise ProtocolError("hello.client_id must be a non-empty string")
        if not isinstance(capabilities, list) or not all(
            isinstance(capability, str) for capability in capabilities
        ):
            raise ProtocolError("hello.capabilities must be a string list")
        return client_id, capabilities

    async def _write_client_messages(
        self, websocket: web.WebSocketResponse, queue: asyncio.Queue[str]
    ) -> None:
        while True:
            await websocket.send_str(await queue.get())

    def _handle_client_message(self, client: _Client, raw: str) -> None:
        try:
            message = parse_message(raw)
        except ProtocolError as error:
            self._enqueue_message(
                client,
                make_message(
                    "control",
                    "error",
                    {"code": "invalid_message", "message": str(error)},
                ),
            )
            return
        if message.channel != "control" or message.message_type != "command":
            self._enqueue_message(
                client,
                make_message(
                    "control",
                    "error",
                    {
                        "code": "unsupported_message",
                        "message": "only control/command is accepted",
                    },
                ),
            )
            return
        command = message.payload.get("command")
        arguments = message.payload.get("arguments", {})
        if not isinstance(command, str) or not isinstance(arguments, dict):
            self._enqueue_message(
                client,
                make_message(
                    "control",
                    "error",
                    {
                        "code": "invalid_command",
                        "message": "command and arguments are invalid",
                    },
                ),
            )
            return
        try:
            self._dispatch_control(command, cast(JsonObject, arguments))
        except ProtocolError as error:
            self._enqueue_message(
                client,
                make_message(
                    "control",
                    "error",
                    {"code": "invalid_command", "message": str(error)},
                ),
            )
            return
        self._enqueue_message(
            client,
            make_message("control", "command_ack", {"command": command}),
        )

    def _dispatch_control(self, command: str, arguments: JsonObject) -> None:
        handlers: dict[str, Callable[[JsonObject], None]] = {
            "toggle_thinking": self._toggle_thinking,
            "reset_context": self._reset_context,
            "reset_module": self._reset_module,
            "set_visibility_mode": self._set_visibility_mode,
            "request_shutdown": self._request_shutdown,
            "request_model_options": self._request_model_options,
            "request_microphone_options": self._request_microphone_options,
            "save_config_selection": self._save_config_selection,
        }
        handler = handlers.get(command)
        if handler is None:
            raise ProtocolError(f"unsupported control command: {command}")
        handler(arguments)

    def _toggle_thinking(self, arguments: JsonObject) -> None:
        del arguments
        self._control_api.toggle_thinking()

    def _reset_context(self, arguments: JsonObject) -> None:
        del arguments
        self._control_api.reset_context()

    def _reset_module(self, arguments: JsonObject) -> None:
        module_id = arguments.get("module_id")
        if not isinstance(module_id, str):
            raise ProtocolError("reset_module requires arguments.module_id")
        self._control_api.reset_module(module_id)

    def _set_visibility_mode(self, arguments: JsonObject) -> None:
        mode = arguments.get("mode")
        if not isinstance(mode, str):
            raise ProtocolError("set_visibility_mode requires arguments.mode")
        self._control_api.set_visibility_mode(mode)

    def _request_shutdown(self, arguments: JsonObject) -> None:
        del arguments
        self._control_api.request_shutdown()

    def _request_model_options(self, arguments: JsonObject) -> None:
        del arguments
        self._control_api.request_model_options()

    def _request_microphone_options(self, arguments: JsonObject) -> None:
        del arguments
        self._control_api.request_microphone_options()

    def _save_config_selection(self, arguments: JsonObject) -> None:
        model = arguments.get("model")
        microphone = arguments.get("microphone")
        if not isinstance(model, str) or not isinstance(microphone, str):
            raise ProtocolError(
                "save_config_selection requires string model and microphone arguments"
            )
        self._control_api.save_config_selection(model, microphone)

    @staticmethod
    async def _close_with_error(
        websocket: web.WebSocketResponse, code: str, message: str = "handshake required"
    ) -> None:
        if not websocket.closed:
            await websocket.send_json(
                make_message("control", "error", {"code": code, "message": message})
            )
            await websocket.close()
