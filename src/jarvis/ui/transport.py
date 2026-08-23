"""Local HTTP+WebSocket transport for Jarvis UI surfaces."""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote, unquote

from aiohttp import web
from aiohttp.multipart import BodyPartReader

from jarvis.audio.tts_mute import TtsSpeechEnabledChanged
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    DEFAULT_FORK_SEED_MAX_CHARS,
    TTS_ROUTE_TYPES,
    DataBoundary,
    Settings,
    TtsLanguageSettings,
    VadSettings,
    tts_field_matches_spec,
    tts_route_field_specs,
)
from jarvis.core.lifecycle import (
    AttachmentSubmissionResult,
    ModelRequestInput,
    ModelRequestStarted,
    NewContextReason,
    NewContextResult,
    PersistedFileOutcome,
    TextSubmissionReason,
    TextSubmissionResult,
)
from jarvis.core.solo_session import SoloSessionChanged
from jarvis.dialog.thinking_mode import ReasoningLevel, ReasoningLevelChanged
from jarvis.inputs.attachment_audio import MAX_CLIP_SECONDS, MAX_CLIPS_PER_FILE
from jarvis.inputs.attachments import (
    MAX_ATTACHMENTS_PER_TURN,
    MAX_TOTAL_UPLOAD_BYTES_PER_TURN,
    AttachmentPlan,
    AttachmentPlanItem,
    AttachmentUpload,
    plan_attachments,
)
from jarvis.journal.annotation import (
    ANNOTATION_MAX_TEXT_LENGTH,
    Annotation,
    AnnotationOverlayChanged,
    AnnotationOverlayRepository,
    AnnotationRead,
    AnnotationSource,
    AnnotationTarget,
    AnnotationWriteStatus,
)
from jarvis.journal.annotation_generator import (
    AnnotationGenerationOutcome,
    AnnotationGenerationResult,
    AnnotationGenerationService,
)
from jarvis.journal.archive import ArchiveMediaOutcome, ArchiveRun
from jarvis.journal.consolidation import (
    ConsolidationPlan,
    ConsolidationPlanner,
    MediaPlanItem,
)
from jarvis.journal.consolidation_executor import ConsolidationExecutor
from jarvis.journal.corpus import HISTORY_SEARCH_MAX_RESULTS
from jarvis.journal.events import JournalEvent, JournalEventAppended, JournalEventRef
from jarvis.journal.fork import ForkSessionReason, ForkSessionResult
from jarvis.journal.lifecycle import (
    HistoryProjectionConsistencyError,
    JournalHistoryService,
)
from jarvis.journal.search import JournalSearchIndex
from jarvis.journal.store import JournalReplay, JournalStore
from jarvis.journal.transcript import (
    TRANSCRIPT_MAX_TEXT_LENGTH,
    TranscriptOverlayChanged,
    TranscriptOverlayRead,
    TranscriptOverlayRepository,
    TranscriptSource,
    TranscriptUpsertStatus,
)
from jarvis.journal.transcription import (
    TranscriptionOutcome,
    TranscriptionResult,
    TranscriptionService,
)
from jarvis.memory.files import (
    MemoryFileId,
    MemoryFileOverCapError,
    MemoryFileRead,
    MemoryFileRepository,
)
from jarvis.tools.interception import ToolCallFinished, ToolCallStarted
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
    microphone_option_payload,
    model_request_log_payload,
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
UPLOAD_READ_CHUNK_BYTES = 64 * 1024
MAX_JOURNAL_UPLOAD_REQUEST_BYTES = MAX_TOTAL_UPLOAD_BYTES_PER_TURN + 1024 * 1024

# ModelRequestStarted.audio_duration_seconds is a single per-turn value that
# applies whichever audio-bearing input produced it - the mic path's AUDIO
# and the attachment path's ATTACHMENT_AUDIO (task-v1.6.0-6) are mutually
# exclusive within one turn, so there is never an ambiguity about which one
# the duration belongs to.
_AUDIO_DURATION_INPUTS = frozenset(
    {ModelRequestInput.AUDIO, ModelRequestInput.ATTACHMENT_AUDIO}
)

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JsonObject = dict[str, JSONValue]


class ProtocolError(ValueError):
    """Raised when a message does not satisfy protocol v1."""


class UploadTooLargeError(Exception):
    def __init__(self, actual_bytes: int, max_bytes: int) -> None:
        super().__init__("multipart attachment upload exceeds the per-turn byte budget")
        self.actual_bytes = actual_bytes
        self.max_bytes = max_bytes


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


def _parse_tts_enabled(raw: JSONValue) -> bool | None:
    if raw is None:
        return None
    if not isinstance(raw, bool):
        raise ProtocolError("tts_enabled must be a boolean")
    return raw


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


def _is_event_position(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@web.middleware
async def journal_input_413_json_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPRequestEntityTooLarge:
        if request.path != "/api/journal/input":
            raise
        return web.json_response(
            {
                "status": "rejected",
                "reason": "request_too_large",
                "actual_bytes": request.content_length or 0,
                "max_bytes": MAX_JOURNAL_UPLOAD_REQUEST_BYTES,
                "files": [],
            },
            status=413,
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


def _parse_persist_indices(raw: bytes) -> set[int]:
    """The `persist` multipart field is a JSON array of 0-based upload indices
    (in upload order) the client marked to keep as session files. Malformed
    input yields no marks rather than an error - persistence is opt-in and a
    bad marker must never reject an otherwise valid submission."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return set()
    if not isinstance(value, list):
        return set()
    return {
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0
    }


def _persistent_outcome_payload(outcome: PersistedFileOutcome) -> JsonObject:
    if outcome.storage_name is not None:
        return {
            "status": "saved",
            "storage_name": outcome.storage_name,
            "bytes": outcome.bytes,
        }
    return {"status": "rejected", "reason": outcome.error}


class ControlApi(Protocol):
    def toggle_thinking(self) -> None: ...

    def set_reasoning_level(self, level_value: str) -> None: ...

    def set_mcp_enabled(self, enabled: bool) -> None: ...

    def set_tts_enabled(self, enabled: bool) -> None: ...

    def set_solo_session_enabled(self, enabled: bool) -> None: ...

    def set_tool_enabled(self, name: str, enabled: bool) -> None: ...

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
        microphone_host_api: str = "",
        ui_language: str | None = None,
        vad: VadSettings | None = None,
        tts_routes: dict[str, TtsLanguageSettings] | None = None,
        tts_enabled: bool | None = None,
    ) -> None: ...


class TextInputSubmitter(Protocol):
    async def __call__(self, text: str) -> TextSubmissionResult: ...


class AttachmentInputSubmitter(Protocol):
    async def __call__(
        self,
        typed_text: str,
        plan: AttachmentPlan,
        persistent_uploads: Sequence[AttachmentUpload] = (),
    ) -> AttachmentSubmissionResult: ...


class NewContextHandler(Protocol):
    async def __call__(self) -> NewContextResult: ...


class JournalForkHandler(Protocol):
    async def __call__(
        self,
        *,
        source_session_id: str,
        replay: JournalReplay,
        source_end_timestamp: str,
        seed_budget_chars: int,
    ) -> ForkSessionResult: ...


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
        tts_enabled: bool = True,
        solo_session_enabled: bool = False,
        language: str = DEFAULT_UI_LANGUAGE,
        config_values: JsonObject | None = None,
        debug: bool = False,
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
            # Fixed for the process's whole run - set once here from the
            # CLI flag, never mutated - but still part of the snapshot, not
            # a one-time push, so a reconnect (or a second client) sees it
            # without depending on catching the original announcement.
            "debug": {"enabled": debug},
            "mcp": {"status": "off", "enabled": False, "tools": []},
            "tts": {"enabled": tts_enabled},
            "solo_session": {"enabled": solo_session_enabled},
            "model": {"label": model_label},
            "system_events": [],
            "thinking": cast(JsonObject, thinking_mode_payload(reasoning_level)),
            "visibility": cast(JsonObject, visibility_mode_payload(visibility_mode)),
            "model_options": {"options": [], "current": model_label},
            "microphone_options": {
                "options": [],
                "current": {"device": "", "host_api": ""},
            },
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

    def set_tts_state(self, enabled: bool) -> JsonObject | None:
        return self._replace("tts", {"enabled": enabled})

    def set_solo_session_state(self, enabled: bool) -> JsonObject | None:
        return self._replace("solo_session", {"enabled": enabled})

    def set_last_model_request(self, summary: ModelRequestSummary) -> JsonObject | None:
        return self._replace(
            "last_model_request", cast(JsonObject, model_request_payload(summary))
        )

    def set_model_label(self, label: str) -> JsonObject | None:
        return self._replace("model", {"label": label})

    def add_system_event(self, event: SystemEvent) -> JsonObject:
        return self._append_event(cast(JsonObject, system_event_payload(event)))

    def add_model_request_event(self, summary: ModelRequestSummary) -> JsonObject:
        """story-v1.6.4-task-2: the panel's user-facing turn record.

        It shares one bounded history with the diagnostics rather than
        getting its own budget: this is one panel, and the durable record
        of what was sent is the file log, not these 200 entries.
        """
        return self._append_event(cast(JsonObject, model_request_log_payload(summary)))

    def _append_event(self, payload: JsonObject) -> JsonObject:
        events = cast(list[JSONValue], self._state["system_events"])
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
        self, options: list[JsonObject], current: JsonObject
    ) -> JsonObject | None:
        """A microphone option is a (device, host_api) pair, not a string:
        one physical microphone appears once per host API under the same
        name, so a name alone cannot identify what the user picked (see
        audio/devices.py)."""
        return self._replace(
            "microphone_options",
            {"options": cast(JSONValue, options), "current": current},
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
        journal_history_service: JournalHistoryService | None = None,
        journal_store: JournalStore | None = None,
        journal_search_index: JournalSearchIndex | None = None,
        journal_text_submitter: TextInputSubmitter | None = None,
        journal_attachment_submitter: AttachmentInputSubmitter | None = None,
        journal_new_context_handler: NewContextHandler | None = None,
        journal_fork_handler: JournalForkHandler | None = None,
        journal_fork_seed_max_chars: int = DEFAULT_FORK_SEED_MAX_CHARS,
        journal_active_session_id: Callable[[], str | None] | None = None,
        journal_transcript_repository: TranscriptOverlayRepository | None = None,
        journal_transcription_service: TranscriptionService | None = None,
        journal_annotation_repository: AnnotationOverlayRepository | None = None,
        journal_annotation_generation_service: (
            AnnotationGenerationService | None
        ) = None,
        journal_consolidation_planner: ConsolidationPlanner | None = None,
        journal_consolidation_executor: ConsolidationExecutor | None = None,
        memory_file_repository: MemoryFileRepository | None = None,
        max_audio_attachment_clips: int = MAX_CLIPS_PER_FILE,
    ) -> None:
        self._bus = bus
        self._control_api = control_api
        self._state = state or UiStateStore()
        self._logger = logger or logging.getLogger(__name__)
        self._host = host
        self._port = port
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._ui_dir = ui_dir
        self._journal_history_service = journal_history_service
        self._journal_store = journal_store
        self._journal_search_index = journal_search_index
        self._journal_text_submitter = journal_text_submitter
        self._journal_attachment_submitter = journal_attachment_submitter
        self._journal_new_context_handler = journal_new_context_handler
        self._journal_fork_handler = journal_fork_handler
        self._journal_fork_seed_max_chars = journal_fork_seed_max_chars
        self._journal_active_session_id = journal_active_session_id or (lambda: None)
        self._journal_transcript_repository = journal_transcript_repository
        self._journal_transcription_service = journal_transcription_service
        self._journal_annotation_repository = journal_annotation_repository
        self._journal_annotation_generation_service = (
            journal_annotation_generation_service
        )
        self._journal_consolidation_planner = journal_consolidation_planner
        self._journal_consolidation_executor = journal_consolidation_executor
        self._memory_file_repository = memory_file_repository
        self._max_audio_attachment_seconds = (
            max_audio_attachment_clips * MAX_CLIP_SECONDS
        )
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
        self._subscribe_to_bus()
        app = web.Application(
            client_max_size=MAX_JOURNAL_UPLOAD_REQUEST_BYTES,
            middlewares=[journal_input_413_json_middleware],
        )
        app.router.add_get("/ws", self._websocket_handler)
        app.router.add_get("/api/journal/sessions", self._journal_sessions_handler)
        app.router.add_post("/api/journal/input", self._journal_input_handler)
        app.router.add_post(
            "/api/journal/context/new", self._journal_new_context_handler_http
        )
        app.router.add_post(
            "/api/journal/sessions/{session_id}/fork",
            self._journal_fork_handler_http,
        )
        app.router.add_get("/api/journal/usage", self._journal_usage_handler)
        app.router.add_get(
            "/api/journal/sessions/{session_id}", self._journal_feed_handler
        )
        app.router.add_delete(
            "/api/journal/sessions/{session_id}", self._journal_delete_handler
        )
        app.router.add_get("/api/journal/search", self._journal_search_handler)
        app.router.add_get(
            "/api/journal/transcripts/{session_id}/{event_position}",
            self._journal_transcript_get_handler,
        )
        app.router.add_put(
            "/api/journal/transcripts/{session_id}/{event_position}",
            self._journal_transcript_put_handler,
        )
        app.router.add_post(
            "/api/journal/transcripts/{session_id}/{event_position}/generate",
            self._journal_transcript_generate_handler,
        )
        app.router.add_get(
            "/api/journal/annotations/{session_id}",
            self._journal_annotation_list_handler,
        )
        app.router.add_post(
            "/api/journal/annotations/{session_id}/generate",
            self._journal_annotation_generate_handler,
        )
        app.router.add_get(
            "/api/journal/annotations/{session_id}/{annotation_id}",
            self._journal_annotation_get_handler,
        )
        app.router.add_put(
            "/api/journal/annotations/{session_id}/{annotation_id}",
            self._journal_annotation_put_handler,
        )
        app.router.add_get(
            "/api/journal/consolidation/{session_id}",
            self._journal_consolidation_plan_handler,
        )
        app.router.add_get(
            "/api/journal/consolidation/{session_id}/status",
            self._journal_consolidation_status_handler,
        )
        app.router.add_post(
            "/api/journal/consolidation/{session_id}/execute",
            self._journal_consolidation_execute_handler,
        )
        app.router.add_get(
            "/api/journal/media/{session_id}/{media_path:.*}",
            self._journal_media_handler,
        )
        app.router.add_get("/api/memory/files/{file_id}", self._memory_file_get_handler)
        app.router.add_put("/api/memory/files/{file_id}", self._memory_file_put_handler)
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

    def set_tts_enabled(self, enabled: bool) -> None:
        self._publish_delta(self._state.set_tts_state(enabled))

    def set_solo_session_enabled(self, enabled: bool) -> None:
        self._publish_delta(self._state.set_solo_session_state(enabled))

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
            (TtsSpeechEnabledChanged, self._on_tts_speech_enabled_changed),
            (SoloSessionChanged, self._on_solo_session_changed),
            (ModuleHealthChanged, self._on_module_health_changed),
            (ModelRequestStarted, self._on_model_request_started),
            (ToolCallStarted, self._on_tool_call_started),
            (ToolCallFinished, self._on_tool_call_finished),
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

    async def _on_tts_speech_enabled_changed(
        self, event: TtsSpeechEnabledChanged
    ) -> None:
        self.set_tts_enabled(event.enabled)

    async def _on_solo_session_changed(self, event: SoloSessionChanged) -> None:
        self.set_solo_session_enabled(event.enabled)

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
                        if input_kind in _AUDIO_DURATION_INPUTS
                        else None
                    ),
                )
                for input_kind in event.inputs
            ),
            prompt_budget=event.prompt_budget,
        )
        self._publish_delta(self._state.set_last_model_request(summary))
        self._publish_delta(self._state.add_model_request_event(summary))

    async def _on_tool_call_started(self, event: ToolCallStarted) -> None:
        self._publish_delta(self._state.record_tool_boundary(event.data_boundary))

    async def _on_tool_call_finished(self, event: ToolCallFinished) -> None:
        # A call whose reach depends on its arguments - a camera capture
        # naming a LAN source - is only known to be wider than its tool's
        # declared boundary once it has run. Recording is monotonic, so a
        # local call finishing after a LAN one cannot pull the axis back.
        self._publish_delta(self._state.record_tool_boundary(event.data_boundary))

    async def _on_model_options_available(self, event: ModelOptionsAvailable) -> None:
        self._publish_delta(self._state.set_model_options(event.options, event.current))

    async def _on_microphone_options_available(
        self, event: MicrophoneOptionsAvailable
    ) -> None:
        self._publish_delta(
            self._state.set_microphone_options(
                [microphone_option_payload(option) for option in event.options],
                microphone_option_payload(event.current),
            )
        )

    async def _on_ui_config_saved(self, event: UiConfigSaved) -> None:
        del event
        self._publish_delta(self._state.set_pending_restart(True))

    async def _on_journal_event_appended(self, event: JournalEventAppended) -> None:
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
        history = self._journal_history_service
        if history is None and self._journal_store is None:
            return web.json_response({"status": "ok", "sessions": []})
        list_sessions = (
            history.list_sessions
            if history is not None
            else self._require_journal_store().list_sessions
        )
        store = history if history is not None else self._require_journal_store()
        return web.json_response(
            {
                "status": "ok",
                "sessions": [
                    journal_session_payload(summary, store)
                    for summary in list_sessions()
                ],
            }
        )

    async def _journal_input_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if request.content_type == "multipart/form-data":
            return await self._journal_multipart_input_handler(request)
        if self._journal_text_submitter is None:
            raise web.HTTPServiceUnavailable(text="journal input not available")
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="request body must be JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise web.HTTPBadRequest(text="request body requires string text")
        result = await self._journal_text_submitter(payload["text"])
        return web.json_response(self._text_submission_payload(result))

    async def _journal_multipart_input_handler(
        self, request: web.Request
    ) -> web.Response:
        if self._journal_attachment_submitter is None:
            raise web.HTTPServiceUnavailable(
                text="journal attachment input not available"
            )
        try:
            (
                typed_text,
                uploads,
                pre_rejected_files,
                persist_indices,
            ) = await self._read_multipart_input(request)
        except UploadTooLargeError as error:
            return web.json_response(
                {
                    "status": "rejected",
                    "reason": "request_too_large",
                    "actual_bytes": error.actual_bytes,
                    "max_bytes": error.max_bytes,
                    "files": [],
                },
                status=413,
            )
        if not uploads:
            if self._journal_text_submitter is None:
                raise web.HTTPServiceUnavailable(text="journal input not available")
            result = await self._journal_text_submitter(typed_text)
            payload = self._text_submission_payload(result)
            payload["files"] = []
            return web.json_response(payload)

        plan = plan_attachments(
            uploads, max_audio_seconds=self._max_audio_attachment_seconds
        )
        persist_order = [
            index for index in sorted(persist_indices) if index < len(uploads)
        ]
        # Persistence rides the same validation gate as transient media: only a
        # planner-accepted upload is written. A marked-but-rejected file is
        # never saved (write_bytes is uncapped, so persisting a file the planner
        # refused for size/type would silently bypass that validation); it is
        # reported persistent-rejected instead.
        persistable_order = [
            index for index in persist_order if plan.items[index].accepted
        ]
        persistent_uploads = [uploads[index] for index in persistable_order]
        result = await self._journal_attachment_submitter(
            typed_text, plan, persistent_uploads
        )
        persistence_by_index: dict[int, JsonObject] = {
            index: _persistent_outcome_payload(outcome)
            for index, outcome in zip(
                persistable_order, result.persisted_files, strict=False
            )
        }
        for index in persist_order:
            if index not in persistence_by_index:
                persistence_by_index[index] = {
                    "status": "rejected",
                    "reason": "attachment was rejected; not saved",
                }
        return web.json_response(
            self._attachment_submission_payload(
                result, plan, pre_rejected_files, persistence_by_index
            )
        )

    async def _read_multipart_input(
        self, request: web.Request
    ) -> tuple[str, list[AttachmentUpload], list[JsonObject], set[int]]:
        try:
            reader = await request.multipart()
        except ValueError:
            raise web.HTTPBadRequest(text="request body must be multipart") from None

        typed_text = ""
        uploads: list[AttachmentUpload] = []
        pre_rejected_files: list[JsonObject] = []
        persist_indices: set[int] = set()
        total_bytes = 0

        async for part in reader:
            if part.filename is None:
                if part.name == "text":
                    raw_text = await self._read_multipart_text_part(part)
                    typed_text = raw_text.decode("utf-8", errors="replace")
                elif part.name == "persist":
                    raw_persist = await self._read_multipart_text_part(part)
                    persist_indices = _parse_persist_indices(raw_persist)
                else:
                    await part.release()
                continue

            filename = self._client_upload_basename(part.filename)
            if len(uploads) >= MAX_ATTACHMENTS_PER_TURN:
                pre_rejected_files.append(
                    {
                        "filename": filename,
                        "status": "rejected",
                        "class": None,
                        "warnings": [],
                        "reason": (
                            f"{filename}: turn already has the maximum of "
                            f"{MAX_ATTACHMENTS_PER_TURN} attachments."
                        ),
                    }
                )
                total_bytes = await self._discard_multipart_part(part, total_bytes)
                continue

            data, total_bytes = await self._read_multipart_part(part, total_bytes)
            uploads.append(
                AttachmentUpload(
                    filename=filename,
                    content_type=part.headers.get("Content-Type", ""),
                    data=data,
                )
            )

        return typed_text, uploads, pre_rejected_files, persist_indices

    async def _read_multipart_text_part(self, part: BodyPartReader) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = await part.read_chunk(size=UPLOAD_READ_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    async def _read_multipart_part(
        self, part: BodyPartReader, total_bytes: int
    ) -> tuple[bytes, int]:
        chunks: list[bytes] = []
        while True:
            chunk = await part.read_chunk(size=UPLOAD_READ_CHUNK_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_TOTAL_UPLOAD_BYTES_PER_TURN:
                raise UploadTooLargeError(
                    actual_bytes=total_bytes, max_bytes=MAX_TOTAL_UPLOAD_BYTES_PER_TURN
                )
            chunks.append(chunk)
        return b"".join(chunks), total_bytes

    async def _discard_multipart_part(
        self, part: BodyPartReader, total_bytes: int
    ) -> int:
        while True:
            chunk = await part.read_chunk(size=UPLOAD_READ_CHUNK_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_TOTAL_UPLOAD_BYTES_PER_TURN:
                raise UploadTooLargeError(
                    actual_bytes=total_bytes, max_bytes=MAX_TOTAL_UPLOAD_BYTES_PER_TURN
                )
        return total_bytes

    async def _journal_new_context_handler_http(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if self._journal_new_context_handler is None:
            raise web.HTTPServiceUnavailable(text="new context not available")
        result = await self._journal_new_context_handler()
        return self._journal_new_context_response(result)

    async def _journal_fork_handler_http(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        history = self._journal_history_service
        if history is None and self._journal_store is None:
            return web.json_response(
                {"status": "rejected", "reason": "unknown_session"}, status=404
            )
        if self._journal_fork_handler is None:
            return web.json_response(
                {"status": "rejected", "reason": "unknown_session"}, status=404
            )
        source_session_id = request.match_info["session_id"]
        read_session = (
            history.read_session
            if history is not None
            else self._require_journal_store().read_session
        )
        replay = await asyncio.to_thread(read_session, source_session_id)
        records = replay.records
        if not records:
            return web.json_response(
                {"status": "rejected", "reason": "unknown_session"}, status=404
            )
        result = await self._journal_fork_handler(
            source_session_id=source_session_id,
            replay=replay,
            source_end_timestamp=records[-1].event.timestamp,
            seed_budget_chars=self._journal_fork_seed_max_chars,
        )
        return self._journal_fork_response(source_session_id, result)

    async def _journal_usage_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        history = self._journal_history_service
        if history is None and self._journal_store is None:
            return web.json_response(
                {
                    "status": "ok",
                    "total_bytes": 0,
                    "active_session_id": self._journal_active_session_id(),
                    "sessions": [],
                }
            )
        usage_reader = history.usage
        if history is None:
            usage_reader = self._require_journal_store().usage
        usage = await asyncio.to_thread(usage_reader)
        return web.json_response(
            {
                "status": "ok",
                "total_bytes": usage.total_bytes,
                "active_session_id": self._journal_active_session_id(),
                "sessions": [
                    {"id": session.session_id, "bytes": session.bytes}
                    for session in usage.sessions
                ],
            }
        )

    async def _journal_feed_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        session_id = request.match_info["session_id"]
        history = self._journal_history_service
        if history is None and self._journal_store is None:
            return web.json_response(
                {"status": "ok", "session_id": session_id, "events": []}
            )
        read_session = (
            history.read_session
            if history is not None
            else self._require_journal_store().read_session
        )
        replay = read_session(session_id)
        return web.json_response(
            {
                "status": "ok",
                "session_id": session_id,
                "events": [
                    journal_event_payload(record.event, self._journal_media_url)
                    for record in replay.records
                ],
            }
        )

    async def _journal_delete_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        session_id = request.match_info["session_id"]
        history = self._journal_history_service
        if history is None:
            return web.json_response(
                {"status": "rejected", "reason": "not_found"}, status=404
            )
        if session_id == self._journal_active_session_id():
            return web.json_response(
                {"status": "rejected", "reason": "active_session"}, status=409
            )
        try:
            await asyncio.to_thread(history.delete_session, session_id)
        except KeyError:
            return web.json_response(
                {"status": "rejected", "reason": "not_found"}, status=404
            )
        except HistoryProjectionConsistencyError:
            return web.json_response(
                {"status": "rejected", "reason": "projection_consistency_failed"},
                status=500,
            )
        return web.json_response({"status": "ok", "deleted_session_id": session_id})

    async def _journal_search_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        limit = self._parse_search_limit(request.query.get("limit"))
        history = self._journal_history_service
        if history is not None:
            hits = history.search(
                request.query.get("query", request.query.get("q", "")),
                date_from=request.query.get("date_from"),
                date_to=request.query.get("date_to"),
                limit=limit,
            )
        elif self._journal_search_index is None:
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

    async def _journal_transcript_get_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if self._journal_transcript_repository is None:
            raise web.HTTPServiceUnavailable(text="transcripts not available")
        reference = self._parse_transcript_reference(request)
        read = await asyncio.to_thread(
            self._journal_transcript_repository.read_transcript, reference
        )
        return web.json_response(self._transcript_read_payload(reference, read))

    async def _journal_transcript_put_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        repository = self._journal_transcript_repository
        if repository is None:
            raise web.HTTPServiceUnavailable(text="transcripts not available")
        reference = self._parse_transcript_reference(request)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="request body must be JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise web.HTTPBadRequest(text="request body requires string text")
        result = await asyncio.to_thread(
            repository.upsert_transcript,
            reference,
            payload["text"],
            TranscriptSource.EDITED,
        )
        if not result.accepted:
            return self._transcript_upsert_rejection(result.status)
        await self._bus.publish(
            TranscriptOverlayChanged, TranscriptOverlayChanged(reference)
        )
        read = await asyncio.to_thread(repository.read_transcript, reference)
        return web.json_response(self._transcript_read_payload(reference, read))

    async def _journal_transcript_generate_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        service = self._journal_transcription_service
        if service is None:
            raise web.HTTPServiceUnavailable(text="transcription not available")
        reference = self._parse_transcript_reference(request)
        result = await service.transcribe_event(reference)
        if result.transcribed:
            await self._bus.publish(
                TranscriptOverlayChanged, TranscriptOverlayChanged(reference)
            )
        return self._transcript_generate_response(reference, result)

    async def _journal_annotation_list_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        repository = self._journal_annotation_repository
        if repository is None:
            raise web.HTTPServiceUnavailable(text="annotations not available")
        session_id = request.match_info["session_id"]
        annotations = await asyncio.to_thread(
            repository.read_session_annotations, session_id
        )
        return web.json_response(
            {
                "status": "ok",
                "session_id": session_id,
                "annotations": [
                    self._annotation_payload(annotation) for annotation in annotations
                ],
            }
        )

    async def _journal_annotation_get_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        repository = self._journal_annotation_repository
        if repository is None:
            raise web.HTTPServiceUnavailable(text="annotations not available")
        session_id = request.match_info["session_id"]
        annotation_id = request.match_info["annotation_id"]
        read = await asyncio.to_thread(repository.read_annotation, annotation_id)
        annotation = self._scoped_annotation(read, session_id)
        if annotation is None:
            raise web.HTTPNotFound(text="annotation not found")
        return web.json_response(
            {"status": "ok", "annotation": self._annotation_payload(annotation)}
        )

    async def _journal_annotation_put_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        repository = self._journal_annotation_repository
        if repository is None:
            raise web.HTTPServiceUnavailable(text="annotations not available")
        session_id = request.match_info["session_id"]
        annotation_id = request.match_info["annotation_id"]
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="request body must be JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise web.HTTPBadRequest(text="request body requires string text")
        read = await asyncio.to_thread(repository.read_annotation, annotation_id)
        if self._scoped_annotation(read, session_id) is None:
            raise web.HTTPNotFound(text="annotation not found")
        result = await asyncio.to_thread(
            repository.update_annotation,
            annotation_id,
            text=payload["text"],
            source=AnnotationSource.EDITED,
        )
        if not result.accepted:
            return self._annotation_write_rejection(result.status)
        await self._bus.publish(
            AnnotationOverlayChanged,
            AnnotationOverlayChanged(session_id, annotation_id),
        )
        read = await asyncio.to_thread(repository.read_annotation, annotation_id)
        annotation = self._scoped_annotation(read, session_id)
        if annotation is None:
            raise web.HTTPNotFound(text="annotation not found")
        return web.json_response(
            {"status": "ok", "annotation": self._annotation_payload(annotation)}
        )

    async def _journal_annotation_generate_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        service = self._journal_annotation_generation_service
        if service is None:
            raise web.HTTPServiceUnavailable(text="annotation generation not available")
        session_id = request.match_info["session_id"]
        target = await self._parse_annotation_generate_target(request, session_id)
        result = await service.generate_annotation(target)
        return self._annotation_generate_response(target, result)

    async def _journal_consolidation_plan_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        planner = self._journal_consolidation_planner
        if planner is None:
            raise web.HTTPServiceUnavailable(
                text="consolidation planning not available"
            )
        session_id = request.match_info["session_id"]
        plan = await asyncio.to_thread(
            planner.plan_far_consolidation,
            session_id,
            active_session_id=self._journal_active_session_id(),
        )
        return web.json_response(
            {"status": "ok", "plan": self._consolidation_plan_payload(plan)}
        )

    async def _journal_consolidation_status_handler(
        self, request: web.Request
    ) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        executor = self._journal_consolidation_executor
        if executor is None:
            raise web.HTTPServiceUnavailable(text="consolidation not available")
        session_id = request.match_info["session_id"]
        read = await asyncio.to_thread(executor.read_last_run, session_id)
        return web.json_response(
            {
                "status": "ok",
                "session_id": session_id,
                "found": read.found,
                "run": (
                    self._archive_run_payload(read.run)
                    if read.run is not None
                    else None
                ),
            }
        )

    async def _journal_consolidation_execute_handler(
        self, request: web.Request
    ) -> web.Response:
        # Destructive: the only endpoint in this file that deletes bytes from
        # disk. No client-supplied plan is ever accepted - the executor
        # always re-derives a fresh plan itself right before acting (owner
        # decision, task v1.8.0-25), so a stale preview fetched earlier by
        # the UI cannot be replayed to bypass the active-session guard or act
        # on since-changed state.
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        executor = self._journal_consolidation_executor
        if executor is None:
            raise web.HTTPServiceUnavailable(text="consolidation not available")
        session_id = request.match_info["session_id"]
        result = await asyncio.to_thread(
            executor.execute_far_consolidation,
            session_id,
            active_session_id_provider=self._journal_active_session_id,
        )
        return web.json_response(
            {
                "status": "ok",
                "session_id": session_id,
                "outcome": result.outcome.value,
                "run": (
                    self._archive_run_payload(result.run)
                    if result.run is not None
                    else None
                ),
            }
        )

    @staticmethod
    def _event_ref_payload(reference: JournalEventRef) -> JsonObject:
        return {
            "session_id": reference.session_id,
            "event_position": reference.event_position,
        }

    @staticmethod
    def _consolidation_plan_payload(plan: ConsolidationPlan) -> JsonObject:
        raw_text_range = None
        if plan.raw_text_range is not None:
            raw_text_range = {
                "start": UiTransportServer._event_ref_payload(
                    plan.raw_text_range.start
                ),
                "end": UiTransportServer._event_ref_payload(plan.raw_text_range.end),
            }
        return {
            "session_id": plan.session_id,
            "plan_status": plan.status.value,
            "event_count": plan.event_count,
            "raw_text_range": raw_text_range,
            "annotation_count": plan.annotation_count,
            "media_items": [
                UiTransportServer._media_plan_item_payload(item)
                for item in plan.media_items
            ],
            "removable_count": len(plan.removable_media),
            "projection_updates_required": list(plan.projection_updates_required),
        }

    @staticmethod
    def _media_plan_item_payload(item: MediaPlanItem) -> JsonObject:
        return {
            "reference": UiTransportServer._event_ref_payload(item.reference),
            "media": item.media,
            "action": item.action.value,
            "reason": item.reason.value,
        }

    @staticmethod
    def _archive_run_payload(run: ArchiveRun) -> JsonObject:
        return {
            "status": run.status.value,
            "event_count": run.event_count,
            "annotation_count": run.annotation_count,
            "bytes_reclaimed": run.bytes_reclaimed,
            "removed_count": run.removed_count,
            "failed_count": run.failed_count,
            "media_outcomes": [
                UiTransportServer._archive_media_outcome_payload(item)
                for item in run.media_outcomes
            ],
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }

    @staticmethod
    def _archive_media_outcome_payload(item: ArchiveMediaOutcome) -> JsonObject:
        return {
            "reference": UiTransportServer._event_ref_payload(item.reference),
            "media": item.media,
            "outcome": item.outcome.value,
            "detail": item.detail,
        }

    async def _journal_media_handler(self, request: web.Request) -> web.StreamResponse:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if self._journal_history_service is None and self._journal_store is None:
            raise web.HTTPNotFound(text="journal media not available")
        media_path = self._resolve_journal_media_path(
            request.match_info["session_id"], request.match_info["media_path"]
        )
        content_type = JOURNAL_MEDIA_TYPES[media_path.suffix.casefold()]
        return web.FileResponse(media_path, headers={"Content-Type": content_type})

    async def _memory_file_get_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if self._memory_file_repository is None:
            raise web.HTTPServiceUnavailable(text="memory files not available")
        file_id = self._parse_memory_file_id(request)
        read = await asyncio.to_thread(self._memory_file_repository.read, file_id)
        return web.json_response(self._memory_file_payload(read))

    async def _memory_file_put_handler(self, request: web.Request) -> web.Response:
        self._require_http_token(request)
        if self._is_hidden():
            return self._journal_hidden_response()
        if self._memory_file_repository is None:
            raise web.HTTPServiceUnavailable(text="memory files not available")
        file_id = self._parse_memory_file_id(request)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="request body must be JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
            raise web.HTTPBadRequest(text="request body requires string content")
        try:
            read = await asyncio.to_thread(
                self._memory_file_repository.write, file_id, payload["content"]
            )
        except MemoryFileOverCapError as error:
            return web.json_response(
                {
                    "status": "rejected",
                    "reason": "over_limit",
                    "chars": error.chars,
                    "max_chars": error.max_chars,
                },
                status=413,
            )
        return web.json_response(self._memory_file_payload(read))

    def _require_http_token(self, request: web.Request) -> None:
        if not token_matches(self.token, request.query.get("token")):
            raise web.HTTPUnauthorized(text="invalid UI transport token")

    def _is_hidden(self) -> bool:
        return self._visibility_mode is VisibilityMode.HIDDEN

    @staticmethod
    def _journal_hidden_response() -> web.Response:
        return web.json_response({"status": "hidden"})

    @staticmethod
    def _parse_transcript_reference(request: web.Request) -> JournalEventRef:
        try:
            position = int(request.match_info["event_position"])
        except ValueError:
            raise web.HTTPBadRequest(text="event_position must be an integer") from None
        try:
            return JournalEventRef(request.match_info["session_id"], position)
        except ValueError:
            raise web.HTTPBadRequest(text="invalid transcript reference") from None

    @staticmethod
    def _transcript_read_payload(
        reference: JournalEventRef, read: TranscriptOverlayRead
    ) -> JsonObject:
        overlay = read.overlay
        payload: JsonObject = {
            "status": "ok",
            "reference": {
                "session_id": reference.session_id,
                "event_position": reference.event_position,
            },
            "found": overlay is not None,
            "transcript": None,
        }
        if overlay is not None:
            payload["transcript"] = {
                "text": overlay.text,
                "source": overlay.source.value,
                "created_at": overlay.created_at,
                "updated_at": overlay.updated_at,
            }
        return payload

    @staticmethod
    def _transcript_upsert_rejection(status: TranscriptUpsertStatus) -> web.Response:
        codes = {
            TranscriptUpsertStatus.UNKNOWN_REFERENCE: 404,
            TranscriptUpsertStatus.TEXT_EMPTY: 400,
            TranscriptUpsertStatus.TEXT_TOO_LONG: 413,
            TranscriptUpsertStatus.INVALID_SOURCE: 400,
        }
        body: JsonObject = {"status": "rejected", "reason": status.value}
        if status is TranscriptUpsertStatus.TEXT_TOO_LONG:
            body["max_chars"] = TRANSCRIPT_MAX_TEXT_LENGTH
        return web.json_response(body, status=codes.get(status, 400))

    def _transcript_generate_response(
        self, reference: JournalEventRef, result: TranscriptionResult
    ) -> web.Response:
        reference_payload = {
            "session_id": reference.session_id,
            "event_position": reference.event_position,
        }
        if result.transcribed:
            return web.json_response(
                {
                    "status": "ok",
                    "reference": reference_payload,
                    "outcome": result.outcome.value,
                    "transcript": result.transcript,
                }
            )
        codes = {
            TranscriptionOutcome.UNKNOWN_EVENT: 404,
            TranscriptionOutcome.NO_AUDIO_MEDIA: 409,
            TranscriptionOutcome.MEDIA_UNREADABLE: 500,
            TranscriptionOutcome.EMPTY_TRANSCRIPT: 422,
            TranscriptionOutcome.TRANSCRIPT_REJECTED: 500,
            TranscriptionOutcome.BACKEND_FAILED: 502,
            TranscriptionOutcome.CANCELLED: 409,
        }
        return web.json_response(
            {
                "status": "rejected",
                "reference": reference_payload,
                "reason": result.outcome.value,
                "detail": result.detail,
            },
            status=codes.get(result.outcome, 500),
        )

    @staticmethod
    def _annotation_payload(annotation: Annotation) -> JsonObject:
        return {
            "annotation_id": annotation.annotation_id,
            "target": {
                "session_id": annotation.target.session_id,
                "start_position": annotation.target.start_position,
                "end_position": annotation.target.end_position,
            },
            "text": annotation.text,
            "author": annotation.author,
            "source": annotation.source.value,
            "status": annotation.status.value,
            "created_at": annotation.created_at,
            "updated_at": annotation.updated_at,
            "metadata": cast(JsonObject, annotation.metadata),
        }

    @staticmethod
    def _scoped_annotation(read: AnnotationRead, session_id: str) -> Annotation | None:
        annotation = read.annotation if read.found else None
        if annotation is None or annotation.target.session_id != session_id:
            return None
        return annotation

    @staticmethod
    def _annotation_write_rejection(status: AnnotationWriteStatus) -> web.Response:
        codes = {
            AnnotationWriteStatus.UNKNOWN_ANNOTATION: 404,
            AnnotationWriteStatus.TEXT_TOO_LONG: 413,
        }
        body: JsonObject = {"status": "rejected", "reason": status.value}
        if status is AnnotationWriteStatus.TEXT_TOO_LONG:
            body["max_chars"] = ANNOTATION_MAX_TEXT_LENGTH
        return web.json_response(body, status=codes.get(status, 400))

    @staticmethod
    async def _parse_annotation_generate_target(
        request: web.Request, session_id: str
    ) -> AnnotationTarget:
        raw = await request.read()
        if not raw:
            return AnnotationTarget(session_id)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="request body must be JSON") from None
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="request body must be a JSON object")
        unknown = set(payload) - {"start_position", "end_position"}
        if unknown:
            raise web.HTTPBadRequest(
                text="body accepts only start_position and end_position"
            )
        start = payload.get("start_position")
        end = payload.get("end_position")
        if start is None and end is None:
            return AnnotationTarget(session_id)
        if not (_is_event_position(start) and _is_event_position(end)):
            raise web.HTTPBadRequest(
                text="start_position and end_position must both be integers >= 0"
            )
        if start > end:
            raise web.HTTPBadRequest(text="start_position must be <= end_position")
        return AnnotationTarget(session_id, start, end)

    def _annotation_generate_response(
        self, target: AnnotationTarget, result: AnnotationGenerationResult
    ) -> web.Response:
        target_payload = {
            "session_id": target.session_id,
            "start_position": target.start_position,
            "end_position": target.end_position,
        }
        if result.generated:
            return web.json_response(
                {
                    "status": "ok",
                    "target": target_payload,
                    "outcome": result.outcome.value,
                    "annotation_id": result.annotation_id,
                    "annotation": result.annotation,
                }
            )
        codes = {
            AnnotationGenerationOutcome.UNKNOWN_RANGE: 404,
            AnnotationGenerationOutcome.SOURCE_TOO_LARGE: 413,
            AnnotationGenerationOutcome.SOURCE_TEXT_TOO_LARGE: 413,
            AnnotationGenerationOutcome.EMPTY_SOURCE: 409,
            AnnotationGenerationOutcome.EMPTY_ANNOTATION: 422,
            AnnotationGenerationOutcome.OUTPUT_TOO_LONG: 422,
            AnnotationGenerationOutcome.ANNOTATION_REJECTED: 500,
            AnnotationGenerationOutcome.BACKEND_FAILED: 502,
            AnnotationGenerationOutcome.CANCELLED: 409,
        }
        return web.json_response(
            {
                "status": "rejected",
                "target": target_payload,
                "reason": result.outcome.value,
                "detail": result.detail,
            },
            status=codes.get(result.outcome, 500),
        )

    @staticmethod
    def _memory_file_payload(read: MemoryFileRead) -> JsonObject:
        return {
            "status": "ok",
            "file": read.file_id.value,
            "content": read.content,
            "chars": read.chars,
            "max_chars": read.max_chars,
        }

    @staticmethod
    def _parse_memory_file_id(request: web.Request) -> MemoryFileId:
        try:
            return MemoryFileId(request.match_info["file_id"])
        except ValueError:
            raise web.HTTPBadRequest(
                text=json.dumps(
                    {"status": "rejected", "reason": "invalid_file"},
                    separators=(",", ":"),
                ),
                content_type="application/json",
            ) from None

    @staticmethod
    def _text_submission_payload(result: TextSubmissionResult) -> JsonObject:
        if result.reason is TextSubmissionReason.ACCEPTED:
            return {"status": "accepted", "reason": result.reason.value}
        return {
            "status": "rejected",
            "reason": result.reason.value,
            "max_chars": result.max_chars,
        }

    @staticmethod
    def _attachment_submission_payload(
        result: AttachmentSubmissionResult,
        plan: AttachmentPlan,
        pre_rejected_files: Sequence[JsonObject],
        persistence_by_index: Mapping[int, JsonObject] | None = None,
    ) -> JsonObject:
        status = "accepted" if result.accepted else "rejected"
        # plan.items is 1:1 with uploads, so an upload index maps a persistence
        # outcome (built by the handler from the persist markers) onto its file.
        persistence = persistence_by_index or {}
        return {
            "status": status,
            "reason": result.reason.value,
            "files": [
                *(
                    UiTransportServer._attachment_item_payload(
                        item, persistence.get(index)
                    )
                    for index, item in enumerate(plan.items)
                ),
                *pre_rejected_files,
            ],
        }

    @staticmethod
    def _attachment_item_payload(
        item: AttachmentPlanItem,
        persistence: JsonObject | None = None,
    ) -> JsonObject:
        if not item.accepted:
            status = "rejected"
        elif item.warnings:
            status = "warning"
        else:
            status = "accepted"
        payload: JsonObject = {
            "filename": item.filename,
            "status": status,
            "class": item.attachment_class.value if item.attachment_class else None,
            "warnings": list(item.warnings),
        }
        if item.rejection_reason is not None:
            payload["reason"] = item.rejection_reason
        if persistence is not None:
            payload["persistent"] = persistence
        return payload

    @staticmethod
    def _client_upload_basename(filename: str) -> str:
        normalized = unquote(filename).replace("\\", "/")
        return normalized.rsplit("/", maxsplit=1)[-1]

    @staticmethod
    def _journal_fork_response(
        source_session_id: str, result: ForkSessionResult
    ) -> web.Response:
        if result.reason is ForkSessionReason.ACCEPTED:
            seed = result.drop_report
            if seed is None:
                raise RuntimeError("accepted fork result requires a seed report")
            return web.json_response(
                {
                    "status": "ok",
                    "session_id": result.new_session_id,
                    "continued_from": source_session_id,
                    "provenance": result.provenance_text,
                    "seed": {
                        "dropped_turns": seed.dropped_turns,
                        "skipped_events": seed.skipped_events,
                        "excluded_events": seed.excluded_events,
                        "truncated": seed.truncated,
                        "max_chars": result.max_chars,
                    },
                }
            )
        if result.reason is ForkSessionReason.BUSY:
            return web.json_response(
                {"status": "rejected", "reason": "busy"}, status=409
            )
        if result.reason is ForkSessionReason.OVERSIZE_TURN:
            return web.json_response(
                {
                    "status": "rejected",
                    "reason": "oversize_turn",
                    "turn_chars": result.oversize_turn_chars,
                    "max_chars": result.max_chars,
                },
                status=409,
            )
        raise RuntimeError(f"unsupported fork result reason: {result.reason}")

    @staticmethod
    def _journal_new_context_response(result: NewContextResult) -> web.Response:
        if result.reason is NewContextReason.ACCEPTED:
            return web.json_response(
                {
                    "status": "ok",
                    "session_id": result.session_id,
                    "provenance": result.provenance_text,
                }
            )
        if result.reason is NewContextReason.BUSY:
            return web.json_response(
                {"status": "rejected", "reason": "busy"}, status=409
            )
        raise RuntimeError(f"unsupported new context result reason: {result.reason}")

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
        if limit > HISTORY_SEARCH_MAX_RESULTS:
            raise web.HTTPBadRequest(
                text=f"limit must be at most {HISTORY_SEARCH_MAX_RESULTS}"
            )
        return limit

    def _journal_media_url(self, event: JournalEvent, media_path: str) -> str:
        return (
            "/api/journal/media/"
            f"{quote(event.session_id, safe='')}/"
            f"{quote(media_path, safe='/')}?token={quote(self.token, safe='')}"
        )

    def _resolve_journal_media_path(self, session_id: str, media_path: str) -> Path:
        if self._journal_history_service is not None:
            root = self._journal_history_service.root.resolve()
        elif self._journal_store is not None:
            root = self._journal_store.root.resolve()
        else:
            raise web.HTTPNotFound(text="journal media not available")
        candidate = (root / session_id / media_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise web.HTTPNotFound(text="journal media not found") from None
        suffix = candidate.suffix.casefold()
        if suffix not in JOURNAL_MEDIA_TYPES or not candidate.is_file():
            raise web.HTTPNotFound(text="journal media not found")
        return candidate

    def _require_journal_store(self) -> JournalStore:
        if self._journal_store is None:
            raise RuntimeError("journal store is not configured")
        return self._journal_store

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
            "set_tts_enabled": self._set_tts_enabled,
            "set_solo_session_enabled": self._set_solo_session_enabled,
            "set_tool_enabled": self._set_tool_enabled,
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

    def _set_tts_enabled(self, arguments: JsonObject) -> None:
        enabled = arguments.get("enabled")
        if not isinstance(enabled, bool):
            raise ProtocolError("set_tts_enabled requires arguments.enabled boolean")
        self._control_api.set_tts_enabled(enabled)

    def _set_solo_session_enabled(self, arguments: JsonObject) -> None:
        enabled = arguments.get("enabled")
        if not isinstance(enabled, bool):
            raise ProtocolError(
                "set_solo_session_enabled requires arguments.enabled boolean"
            )
        self._control_api.set_solo_session_enabled(enabled)

    def _set_tool_enabled(self, arguments: JsonObject) -> None:
        name = arguments.get("name")
        enabled = arguments.get("enabled")
        if not isinstance(name, str) or not name:
            raise ProtocolError("set_tool_enabled requires arguments.name")
        if not isinstance(enabled, bool):
            raise ProtocolError("set_tool_enabled requires arguments.enabled boolean")
        self._control_api.set_tool_enabled(name, enabled)

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
        # Absent means "the front-end did not name a host API", which is
        # the same thing an untouched pre-host_api config says: resolve by
        # name and fail if that is ambiguous.
        microphone_host_api = arguments.get("microphone_host_api", "")
        if not isinstance(microphone_host_api, str):
            raise ProtocolError(
                "save_config_selection requires a string microphone_host_api argument"
            )
        self._control_api.save_config_selection(
            model,
            microphone,
            microphone_host_api=microphone_host_api,
            ui_language=_parse_ui_language(arguments.get("ui_language")),
            vad=_parse_vad(arguments.get("vad")),
            tts_routes=_parse_tts_routes(arguments.get("tts_routes")),
            tts_enabled=_parse_tts_enabled(arguments.get("tts_enabled")),
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
