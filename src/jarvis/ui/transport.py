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
from urllib.parse import quote

from aiohttp import web

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    TTS_ROUTE_TYPES,
    DataBoundary,
    Settings,
    TtsLanguageSettings,
    VadSettings,
    tts_field_matches_spec,
    tts_route_field_specs,
)
from jarvis.core.lifecycle import ModelRequestInput, ModelRequestStarted
from jarvis.dialog.thinking_mode import ReasoningLevel, ReasoningLevelChanged
from jarvis.journal.events import JournalEvent, JournalEventAppended
from jarvis.journal.search import JournalSearchIndex
from jarvis.journal.store import JournalStore
from jarvis.tools.interception import ToolCallStarted
from jarvis.ui.contract import (
    DataLocality,
    DataSource,
    ModelRequestItem,
    ModelRequestSummary,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
    VisibilityMode,
)
from jarvis.ui.module_health import ModuleHealthChanged
from jarvis.ui.status_console import (
    MicrophoneOptionsAvailable,
    ModelOptionsAvailable,
    StatusConsoleApi,
    UiConfigSaved,
    config_values_payload,
    data_locality_payload,
    data_source_payload,
    journal_event_payload,
    journal_search_hit_payload,
    journal_session_payload,
    model_request_payload,
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
JOURNAL_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

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


def _parse_ui_language(raw: JSONValue) -> str | None:
    """Shape/type checks only; value semantics belong to
    config_selection.validate_selection() behind the control API."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ProtocolError("ui_language must be a string")
    return raw


def _parse_vad(raw: JSONValue) -> VadSettings | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProtocolError("vad must be an object")
    fields = {
        "threshold": float,
        "max_chunk_seconds": int,
        "request_end_pause_seconds": float,
        "resume_cooldown_seconds": float,
    }
    if set(raw) != set(fields):
        raise ProtocolError("vad requires exactly: " + ", ".join(sorted(fields)))
    kwargs: dict[str, float | int] = {}
    for name, kind in fields.items():
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ProtocolError(f"vad.{name} must be a number")
        if kind is int and not isinstance(value, int):
            raise ProtocolError(f"vad.{name} must be an integer")
        kwargs[name] = kind(value)
    return VadSettings(**kwargs)  # type: ignore[arg-type]


def _parse_tts_routes(raw: JSONValue) -> dict[str, TtsLanguageSettings] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProtocolError("tts_routes must be an object")
    routes: dict[str, TtsLanguageSettings] = {}
    for language, route_raw in raw.items():
        if not isinstance(route_raw, dict):
            raise ProtocolError(f"tts_routes[{language}] must be an object")
        engine = route_raw.get("engine")
        if not isinstance(engine, str) or engine not in TTS_ROUTE_TYPES:
            raise ProtocolError(f"tts_routes[{language}].engine is invalid")
        specs = tts_route_field_specs(engine)
        expected_fields = {"engine", *(spec.name for spec in specs)}
        if set(route_raw) != expected_fields:
            raise ProtocolError(
                f"tts_routes[{language}] requires exactly: "
                + ", ".join(sorted(expected_fields))
            )
        values: dict[str, object] = {}
        for spec in specs:
            value = route_raw[spec.name]
            if not tts_field_matches_spec(value, spec):
                raise ProtocolError(
                    f"tts_routes[{language}].{spec.name} must be {spec.kind}"
                )
            values[spec.name] = value
        routes[language] = TTS_ROUTE_TYPES[engine](**values)  # type: ignore[arg-type]
    return routes


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

    def set_reasoning_level(self, level_value: str) -> None: ...

    def set_mcp_enabled(self, enabled: bool) -> None: ...

    def reset_context(self) -> None: ...

    def reset_module(self, module_id: str) -> None: ...

    def set_visibility_mode(self, mode_value: str) -> None: ...

    def request_shutdown(self) -> None: ...

    def request_model_options(self) -> None: ...

    def request_microphone_options(self) -> None: ...

    def save_config_selection(
        self,
        model: str,
        microphone_device: str,
        *,
        ui_language: str | None = None,
        vad: VadSettings | None = None,
        tts_routes: dict[str, TtsLanguageSettings] | None = None,
    ) -> None: ...


class UiStateStore:
    """Owns the JSON state projection shared by all UI clients."""

    def __init__(
        self,
        *,
        model_label: str = "",
        runtime_state: RuntimeState = RuntimeState.IDLE,
        data_locality: DataLocality = DataLocality.LOCAL,
        data_source: DataSource = DataSource.LOCAL_ONLY,
        reasoning_level: ReasoningLevel = ReasoningLevel.OFF,
        visibility_mode: VisibilityMode = VisibilityMode.OPEN,
        language: str = DEFAULT_UI_LANGUAGE,
        config_values: JsonObject | None = None,
    ) -> None:
        self._language = language
        self._state: JsonObject = {
            "runtime": cast(
                JsonObject, runtime_state_payload(runtime_state, language=language)
            ),
            "modules": {},
            "last_model_request": {"timestamp": None, "items": []},
            "data_locality": cast(JsonObject, data_locality_payload(data_locality)),
            "data_source": cast(JsonObject, data_source_payload(data_source)),
            "mcp": {"status": "off", "enabled": False, "tools": []},
            "model": {"label": model_label},
            "system_events": [],
            "thinking": cast(JsonObject, thinking_mode_payload(reasoning_level)),
            "visibility": cast(JsonObject, visibility_mode_payload(visibility_mode)),
            "model_options": {"options": [], "current": model_label},
            "microphone_options": {"options": [], "current": ""},
            "pending_restart": {"pending": False},
            "ui_language": {"language": language},
            "config_values": cast(
                JsonObject, config_values or config_values_payload(Settings())
            ),
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

    def set_data_source(self, source: DataSource) -> JsonObject | None:
        return self._replace(
            "data_source", cast(JsonObject, data_source_payload(source))
        )

    def record_tool_boundary(self, boundary: DataBoundary) -> JsonObject | None:
        source_by_boundary = {
            DataBoundary.LOCAL: DataSource.LOCAL_ONLY,
            DataBoundary.LAN: DataSource.LAN,
            DataBoundary.INTERNET: DataSource.INTERNET,
            DataBoundary.UNKNOWN: DataSource.UNKNOWN,
        }
        precedence = {
            DataSource.LOCAL_ONLY: 0,
            DataSource.UNKNOWN: 1,
            DataSource.LAN: 2,
            DataSource.INTERNET: 3,
        }
        current_payload = cast(JsonObject, self._state["data_source"])
        current = DataSource(cast(str, current_payload["source"]))
        candidate = source_by_boundary[boundary]
        if precedence[candidate] <= precedence[current]:
            return None
        return self.set_data_source(candidate)

    def set_mcp_state(self, state: JsonObject) -> JsonObject | None:
        return self._replace("mcp", state)

    def set_last_model_request(self, summary: ModelRequestSummary) -> JsonObject | None:
        return self._replace(
            "last_model_request", cast(JsonObject, model_request_payload(summary))
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

    def set_thinking_mode(self, level: ReasoningLevel) -> JsonObject | None:
        return self._replace("thinking", cast(JsonObject, thinking_mode_payload(level)))

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
        journal_store: JournalStore | None = None,
        journal_search_index: JournalSearchIndex | None = None,
    ) -> None:
        self._bus = bus
        self._control_api = control_api
        self._state = state or UiStateStore()
        self._logger = logger or logging.getLogger(__name__)
        self._host = host
        self._port = port
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._ui_dir = ui_dir
        self._journal_store = journal_store
        self._journal_search_index = journal_search_index
        visibility = cast(JsonObject, self._state.snapshot()["visibility"])
        self._visibility_mode = VisibilityMode(cast(str, visibility["mode"]))
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
        await self._rebuild_journal_index()
        self._subscribe_to_bus()
        app = web.Application()
        app.router.add_get("/ws", self._websocket_handler)
        app.router.add_get("/api/journal/sessions", self._journal_sessions_handler)
        app.router.add_get(
            "/api/journal/sessions/{session_id}", self._journal_feed_handler
        )
        app.router.add_get("/api/journal/search", self._journal_search_handler)
        app.router.add_get(
            "/api/journal/media/{session_id}/{media_path:.*}",
            self._journal_media_handler,
        )
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

    def set_data_source(self, source: DataSource) -> None:
        self._publish_delta(self._state.set_data_source(source))

    def set_mcp_state(self, state: JsonObject) -> None:
        self._publish_delta(self._state.set_mcp_state(state))

    def set_last_model_request(self, summary: ModelRequestSummary) -> None:
        self._publish_delta(self._state.set_last_model_request(summary))

    def set_model_label(self, label: str) -> None:
        self._publish_delta(self._state.set_model_label(label))

    def set_thinking_mode(self, level: ReasoningLevel) -> None:
        self._publish_delta(self._state.set_thinking_mode(level))

    def set_visibility_mode(self, mode: VisibilityMode) -> None:
        self._visibility_mode = mode
        self._publish_delta(self._state.set_visibility_mode(mode))

    def _subscribe_to_bus(self) -> None:
        subscriptions: list[tuple[type[object], Callable[..., object]]] = [
            (SystemEvent, self._on_system_event),
            (ReasoningLevelChanged, self._on_reasoning_level_changed),
            (VisibilityModeChanged, self._on_visibility_mode_changed),
            (ModuleHealthChanged, self._on_module_health_changed),
            (ModelRequestStarted, self._on_model_request_started),
            (ToolCallStarted, self._on_tool_call_started),
            (ModelOptionsAvailable, self._on_model_options_available),
            (MicrophoneOptionsAvailable, self._on_microphone_options_available),
            (UiConfigSaved, self._on_ui_config_saved),
            (JournalEventAppended, self._on_journal_event_appended),
        ]
        for event_type, handler in subscriptions:
            self._bus.subscribe(event_type, cast(Callable[..., object], handler))
        self._subscriptions = subscriptions

    async def _on_system_event(self, event: SystemEvent) -> None:
        # Runtime-state reaction to errors lives in RuntimeStateTracker;
        # this server only projects state it is told about.
        self._publish_delta(self._state.add_system_event(event))

    async def _on_reasoning_level_changed(self, event: ReasoningLevelChanged) -> None:
        self._publish_delta(self._state.set_thinking_mode(event.level))

    async def _on_visibility_mode_changed(self, event: VisibilityModeChanged) -> None:
        self.set_visibility_mode(event.mode)

    async def _on_module_health_changed(self, event: ModuleHealthChanged) -> None:
        # One mechanism for every module (v1.2.14 task 2): the tracker
        # decides status, this server localizes the detail and projects it.
        health = ModuleHealth(
            module=event.module,
            status=event.status,
            detail=ui_text(event.detail_key, self._state.language),
        )
        self._publish_delta(self._state.set_module_health(health))

    async def _on_model_request_started(self, event: ModelRequestStarted) -> None:
        self._publish_delta(self._state.set_data_source(DataSource.LOCAL_ONLY))
        summary = ModelRequestSummary(
            timestamp=event.timestamp,
            items=tuple(
                ModelRequestItem(
                    kind=input_kind,
                    audio_duration_seconds=(
                        event.audio_duration_seconds
                        if input_kind is ModelRequestInput.AUDIO
                        else None
                    ),
                )
                for input_kind in event.inputs
            ),
        )
        self._publish_delta(self._state.set_last_model_request(summary))

    async def _on_tool_call_started(self, event: ToolCallStarted) -> None:
        self._publish_delta(self._state.record_tool_boundary(event.data_boundary))

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

    async def _on_journal_event_appended(self, event: JournalEventAppended) -> None:
        await self._update_journal_index(event.event.session_id)
        if self._is_hidden():
            return
        self._publish_delta(
            make_message(
                "state",
                "delta",
                {
                    "key": "journal_event",
                    "value": journal_event_payload(
                        event.event, self._journal_media_url
                    ),
                },
            )
        )

    async def _journal_sessions_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if self._journal_store is None:
            return web.json_response({"status": "ok", "sessions": []})
        return web.json_response(
            {
                "status": "ok",
                "sessions": [
                    journal_session_payload(summary, self._journal_store)
                    for summary in self._journal_store.list_sessions()
                ],
            }
        )

    async def _journal_feed_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        session_id = request.match_info["session_id"]
        if self._journal_store is None:
            return web.json_response(
                {"status": "ok", "session_id": session_id, "events": []}
            )
        replay = self._journal_store.read_session(session_id)
        return web.json_response(
            {
                "status": "ok",
                "session_id": session_id,
                "events": [
                    journal_event_payload(event, self._journal_media_url)
                    for event in replay.events
                ],
            }
        )

    async def _journal_search_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        limit = self._parse_search_limit(request.query.get("limit"))
        if self._journal_search_index is None:
            hits = []
        else:
            hits = self._journal_search_index.search(
                request.query.get("query", request.query.get("q", "")),
                date_from=request.query.get("date_from"),
                date_to=request.query.get("date_to"),
                limit=limit,
            )
        return web.json_response(
            {
                "status": "ok",
                "hits": [journal_search_hit_payload(hit) for hit in hits],
            }
        )

    async def _journal_media_handler(self, request: web.Request) -> web.StreamResponse:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if self._journal_store is None:
            raise web.HTTPNotFound(text="journal media not available")
        media_path = self._resolve_journal_media_path(
            request.match_info["session_id"], request.match_info["media_path"]
        )
        content_type = JOURNAL_MEDIA_TYPES[media_path.suffix.casefold()]
        return web.FileResponse(media_path, headers={"Content-Type": content_type})

    def _require_http_token(self, request: web.Request) -> None:
        if not token_matches(self.token, request.query.get("token")):
            raise web.HTTPUnauthorized(text="invalid UI transport token")

    def _is_hidden(self) -> bool:
        return self._visibility_mode is VisibilityMode.HIDDEN

    @staticmethod
    def _journal_hidden_response() -> web.Response:
        return web.json_response({"status": "hidden"})

    async def _rebuild_journal_index(self) -> None:
        if self._journal_search_index is None:
            return
        await asyncio.to_thread(self._journal_search_index.rebuild)

    async def _update_journal_index(self, session_id: str) -> None:
        if self._journal_search_index is None:
            return
        await asyncio.to_thread(self._journal_search_index.update_session, session_id)

    @staticmethod
    def _parse_search_limit(raw: str | None) -> int:
        if raw is None:
            return 50
        try:
            limit = int(raw)
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer") from None
        if limit < 1:
            raise web.HTTPBadRequest(text="limit must be positive")
        return limit

    def _journal_media_url(self, event: JournalEvent, media_path: str) -> str:
        return (
            "/api/journal/media/"
            f"{quote(event.session_id, safe='')}/"
            f"{quote(media_path, safe='/')}?token={quote(self.token, safe='')}"
        )

    def _resolve_journal_media_path(self, session_id: str, media_path: str) -> Path:
        if self._journal_store is None:
            raise web.HTTPNotFound(text="journal media not available")
        root = self._journal_store.root.resolve()
        candidate = (root / session_id / media_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise web.HTTPNotFound(text="journal media not found") from None
        suffix = candidate.suffix.casefold()
        if suffix not in JOURNAL_MEDIA_TYPES or not candidate.is_file():
            raise web.HTTPNotFound(text="journal media not found")
        return candidate

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
            "set_reasoning_level": self._set_reasoning_level,
            "set_mcp_enabled": self._set_mcp_enabled,
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

    def _set_reasoning_level(self, arguments: JsonObject) -> None:
        level_value = arguments.get("level")
        if not isinstance(level_value, str):
            raise ProtocolError("set_reasoning_level requires arguments.level")
        try:
            ReasoningLevel(level_value)
        except ValueError:
            raise ProtocolError(f"unknown reasoning level: {level_value!r}") from None
        self._control_api.set_reasoning_level(level_value)

    def _set_mcp_enabled(self, arguments: JsonObject) -> None:
        enabled = arguments.get("enabled")
        if not isinstance(enabled, bool):
            raise ProtocolError("set_mcp_enabled requires arguments.enabled boolean")
        self._control_api.set_mcp_enabled(enabled)

    def _reset_context(self, arguments: JsonObject) -> None:
        del arguments
        self._control_api.reset_context()

    def _reset_module(self, arguments: JsonObject) -> None:
        module_id = arguments.get("module_id")
        if not isinstance(module_id, str):
            raise ProtocolError("reset_module requires arguments.module_id")
        try:
            ModuleId(module_id)
        except ValueError:
            raise ProtocolError(f"unknown module id: {module_id!r}") from None
        self._control_api.reset_module(module_id)

    def _set_visibility_mode(self, arguments: JsonObject) -> None:
        mode = arguments.get("mode")
        if not isinstance(mode, str):
            raise ProtocolError("set_visibility_mode requires arguments.mode")
        try:
            VisibilityMode(mode)
        except ValueError:
            raise ProtocolError(f"unknown visibility mode: {mode!r}") from None
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
        self._control_api.save_config_selection(
            model,
            microphone,
            ui_language=_parse_ui_language(arguments.get("ui_language")),
            vad=_parse_vad(arguments.get("vad")),
            tts_routes=_parse_tts_routes(arguments.get("tts_routes")),
        )

    @staticmethod
    async def _close_with_error(
        websocket: web.WebSocketResponse, code: str, message: str = "handshake required"
    ) -> None:
        if not websocket.closed:
            await websocket.send_json(
                make_message("control", "error", {"code": code, "message": message})
            )
            await websocket.close()
