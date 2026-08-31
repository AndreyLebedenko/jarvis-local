import asyncio
from collections.abc import Sequence
from pathlib import Path

import aiohttp
import pytest

from jarvis.audio.replay import ReplayProgress
from jarvis.audio.tts_mute import TtsSpeechEnabledChanged
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    DEFAULT_FORK_SEED_MAX_CHARS,
    DataBoundary,
    MemorySettings,
    PiperTtsSettings,
    SileroTtsSettings,
    VadSettings,
)
from jarvis.core.lifecycle import (
    AttachmentSubmissionReason,
    AttachmentSubmissionResult,
    ModelRequestInput,
    ModelRequestPassKind,
    ModelRequestStarted,
    NewContextReason,
    NewContextResult,
    PersistedFileOutcome,
    TextSubmissionReason,
    TextSubmissionResult,
)
from jarvis.core.solo_session import SoloSessionChanged
from jarvis.dialog.response_mode import ResponseMode, ResponseModeChanged
from jarvis.dialog.thinking_mode import ReasoningLevel, ReasoningLevelChanged
from jarvis.inputs.attachment_audio import MAX_CLIP_SECONDS, MAX_CLIPS_PER_FILE
from jarvis.inputs.attachments import AttachmentPlan, AttachmentUpload
from jarvis.journal import (
    HISTORY_SEARCH_MAX_RESULTS,
    AnnotationGenerationOutcome,
    AnnotationGenerationResult,
    AnnotationOverlayChanged,
    AnnotationOverlayRepository,
    AnnotationSource,
    AnnotationTarget,
    ArchiveOverlayRepository,
    ConsolidationExecutor,
    ConsolidationPlanner,
    CorpusHistoryProjection,
    HistoryProjectionLifecycle,
    JournalEvent,
    JournalEventAppended,
    JournalEventRef,
    JournalHistoryService,
    JournalRecorder,
    JournalSearchIndex,
    JournalStore,
    JournalStoreConsolidationSource,
    UnavailableSemanticHistoryProjection,
)
from jarvis.journal.fork import (
    ForkSeedDropReport,
    ForkSessionReason,
    ForkSessionResult,
)
from jarvis.journal.lifecycle import JournalStoreEventReferenceResolver
from jarvis.journal.transcript import (
    TranscriptOverlayChanged,
    TranscriptOverlayRepository,
    TranscriptSource,
)
from jarvis.journal.transcription import TranscriptionOutcome, TranscriptionResult
from jarvis.memory.files import (
    MemoryFileId,
    MemoryFileRepository,
    build_memory_file_specs,
)
from jarvis.tools.interception import ToolCallFinished, ToolCallStarted
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
    MAX_SYSTEM_EVENTS,
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

    def set_response_mode(self, mode_value: str) -> None:
        self.calls.append(("set_response_mode", mode_value))

    def set_mcp_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_mcp_enabled", str(enabled)))

    def set_tts_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_tts_enabled", str(enabled)))

    def set_solo_session_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_solo_session_enabled", str(enabled)))

    def set_tool_enabled(self, name: str, enabled: bool) -> None:
        self.calls.append(("set_tool_enabled", name, str(enabled)))

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
        microphone_host_api: str = "",
        ui_language=None,
        response_mode=None,
        vad=None,
        tts_routes=None,
        tts_enabled=None,
    ) -> None:
        self.calls.append(("save_config_selection", f"{model}|{microphone_device}"))
        self.config_kwargs = {
            "microphone_host_api": microphone_host_api,
            "ui_language": ui_language,
            "response_mode": response_mode,
            "vad": vad,
            "tts_routes": tts_routes,
            "tts_enabled": tts_enabled,
        }


class _FakeTextSubmitter:
    def __init__(self, reason: TextSubmissionReason) -> None:
        self.reason = reason
        self.calls: list[str] = []

    async def __call__(self, text: str) -> TextSubmissionResult:
        self.calls.append(text)
        return TextSubmissionResult(self.reason, max_chars=20)


class _FakeAttachmentSubmitter:
    def __init__(
        self,
        reason: AttachmentSubmissionReason,
        persisted_files: tuple[PersistedFileOutcome, ...] = (),
    ) -> None:
        self.reason = reason
        self.persisted_files = persisted_files
        self.calls: list[tuple[str, AttachmentPlan]] = []
        self.persistent_uploads: list[Sequence[AttachmentUpload]] = []

    async def __call__(
        self,
        typed_text: str,
        plan: AttachmentPlan,
        persistent_uploads: Sequence[AttachmentUpload] = (),
    ) -> AttachmentSubmissionResult:
        self.calls.append((typed_text, plan))
        self.persistent_uploads.append(tuple(persistent_uploads))
        return AttachmentSubmissionResult(self.reason, self.persisted_files)


class _FakeJournalForkHandler:
    def __init__(self, result: ForkSessionResult) -> None:
        self.result = result
        self.calls = []

    async def __call__(
        self,
        *,
        source_session_id,
        replay,
        source_end_timestamp,
        seed_budget_chars,
    ) -> ForkSessionResult:
        self.calls.append(
            {
                "source_session_id": source_session_id,
                "replay": replay,
                "source_end_timestamp": source_end_timestamp,
                "seed_budget_chars": seed_budget_chars,
            }
        )
        return self.result


class _FakeNewContextHandler:
    def __init__(self, result: NewContextResult) -> None:
        self.result = result
        self.calls = 0

    async def __call__(self) -> NewContextResult:
        self.calls += 1
        return self.result


class _NoListJournalStore(JournalStore):
    def list_sessions(self):
        raise AssertionError("fork endpoint must not list every session")


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
            prompt_budget={
                "prompt_capacity_tokens": 49152,
                "available_prompt_tokens": 39936,
                "tool_result_reserve_tokens": 8192,
                "reasoning_generation_reserve_tokens": 16384,
                "estimator_safety_margin_tokens": 1024,
                "estimated_prompt_tokens": 24000,
                "headroom_tokens": 15936,
                "base_prompt_tokens": 1200,
                "recent_history_tokens": 20000,
                "retrieval_tokens": 800,
                "recent_history_message_count": 8,
                "retrieval_message_count": 1,
                "truncated_recent_history": True,
                "blank_context_cleared": False,
            },
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
            "prompt_budget": {
                "prompt_capacity_tokens": 49152,
                "available_prompt_tokens": 39936,
                "tool_result_reserve_tokens": 8192,
                "reasoning_generation_reserve_tokens": 16384,
                "estimator_safety_margin_tokens": 1024,
                "estimated_prompt_tokens": 24000,
                "headroom_tokens": 15936,
                "base_prompt_tokens": 1200,
                "recent_history_tokens": 20000,
                "retrieval_tokens": 800,
                "recent_history_message_count": 8,
                "retrieval_message_count": 1,
                "truncated_recent_history": True,
                "blank_context_cleared": False,
            },
        },
    }


@pytest.mark.asyncio
async def test_server_projects_attachment_audio_duration_like_mic_audio():
    """Regression test: _on_model_request_started() used to key the
    duration projection off `input_kind is ModelRequestInput.AUDIO`
    specifically, so an attachment-audio turn's audio_duration_seconds
    (task-v1.6.0-6) was silently dropped from the UI payload even though
    the bus event carried it."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        await bus.publish(
            ModelRequestStarted,
            ModelRequestStarted(
                timestamp=5.0,
                inputs=(ModelRequestInput.ATTACHMENT_AUDIO,),
                audio_duration_seconds=3.5,
            ),
        )
        assert server.state.snapshot()["last_model_request"] == {
            "timestamp": 5.0,
            "items": [{"kind": "attachment_audio", "duration_seconds": 3.5}],
        }
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)


@pytest.mark.asyncio
async def test_server_projects_the_derivative_pass_kind_tag_in_the_event_log():
    """story-v1.9.0 task 3: mode 3's derivative sub-pass must reach the
    events-panel log tagged, not read as an ordinary (untagged) request."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        await bus.publish(
            ModelRequestStarted,
            ModelRequestStarted(
                timestamp=5.0,
                inputs=(),
                audio_duration_seconds=None,
                pass_kind=ModelRequestPassKind.DERIVATIVE,
            ),
        )
        [event] = server.state.snapshot()["system_events"]
        assert event["pass_kind"] == "derivative"
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)


async def test_a_derivative_pass_does_not_touch_the_last_model_request_chip_strip():
    """The chip strip answers "what is true now" for the visible turn
    (see test_model_request_also_lands_in_the_user_facing_event_log's own
    docstring) - a derivative sub-pass is an internal continuation of the
    same turn, not a new user-facing request, so it must not blank out
    pass 1's modality summary there. Nor must it reset the data-source
    badge to local-only, which would silently undo record_tool_boundary's
    own escalation if pass 1 had used an external tool."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        await bus.publish(
            ModelRequestStarted,
            ModelRequestStarted(
                timestamp=1.0,
                inputs=(ModelRequestInput.TEXT_INPUT,),
                audio_duration_seconds=None,
            ),
        )
        server._publish_delta(server.state.record_tool_boundary(DataBoundary.INTERNET))

        await bus.publish(
            ModelRequestStarted,
            ModelRequestStarted(
                timestamp=2.0,
                inputs=(),
                audio_duration_seconds=None,
                pass_kind=ModelRequestPassKind.DERIVATIVE,
            ),
        )

        snapshot = server.state.snapshot()
        assert snapshot["last_model_request"]["timestamp"] == 1.0
        assert snapshot["last_model_request"]["items"] == [{"kind": "text_input"}]
        assert snapshot["data_source"]["source"] == "internet"
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)


@pytest.mark.asyncio
async def test_model_request_also_lands_in_the_user_facing_event_log():
    """story-v1.6.4-task-2: the chip strip answers "what is true now" and
    is replaced every turn; the events panel is where a user scrolls back
    through what earlier turns sent. Both are fed from the same event."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        await bus.publish(
            ModelRequestStarted,
            ModelRequestStarted(
                timestamp=7.0,
                inputs=(ModelRequestInput.AUDIO, ModelRequestInput.SCREENSHOT),
                audio_duration_seconds=2.5,
            ),
        )

        events = server.state.snapshot()["system_events"]
        assert events == [
            {
                "entry": "model_request",
                "timestamp": 7.0,
                "level": "info",
                "items": [
                    {"kind": "audio", "duration_seconds": 2.5},
                    {"kind": "screenshot"},
                ],
            }
        ]
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)


@pytest.mark.asyncio
async def test_model_request_log_entry_carries_no_payload_content():
    """story-v1.6.4 content rule: kinds, counts, durations, sizes - never
    transcript, clipboard text, file names, or image data. The entry is
    built only from the typed inputs, so there is nowhere for content to
    enter, and this test fails loudly if a field is ever added."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        await bus.publish(
            ModelRequestStarted,
            ModelRequestStarted(
                timestamp=8.0,
                inputs=(ModelRequestInput.CLIPBOARD,),
                audio_duration_seconds=None,
            ),
        )

        entry = server.state.snapshot()["system_events"][0]
        assert set(entry) == {"entry", "timestamp", "level", "items"}
        assert entry["items"] == [{"kind": "clipboard"}]
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)


@pytest.mark.asyncio
async def test_model_request_entries_share_the_event_panel_budget():
    """One panel, one bounded history. A request entry is evicted by the
    same MAX_SYSTEM_EVENTS rule as any diagnostic line; the durable
    record is the file log, not this panel."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        for index in range(MAX_SYSTEM_EVENTS + 5):
            await bus.publish(
                ModelRequestStarted,
                ModelRequestStarted(
                    timestamp=float(index),
                    inputs=(ModelRequestInput.AUDIO,),
                    audio_duration_seconds=None,
                ),
            )

        events = server.state.snapshot()["system_events"]
        assert len(events) == MAX_SYSTEM_EVENTS
        assert events[0]["timestamp"] == 5.0
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)


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
    server._dispatch_control("set_response_mode", {"mode": "voice"})
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
        ("set_response_mode", "voice"),
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


@pytest.mark.parametrize("bad_arguments", [{}, {"mode": 3}, {"mode": None}])
def test_set_response_mode_rejects_missing_or_non_string_mode(bad_arguments):
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    with pytest.raises(ProtocolError, match="set_response_mode"):
        server._dispatch_control("set_response_mode", bad_arguments)

    assert control_api.calls == []


def test_set_response_mode_rejects_an_unknown_mode_value():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    with pytest.raises(ProtocolError, match="response mode must be one of"):
        server._dispatch_control("set_response_mode", {"mode": "spoken"})

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
async def test_response_mode_changed_projects_the_mode_value():
    """story-v1.9.0 task 2: a hotkey cycle and a direct UI selection both go
    through ResponseModeState.set_mode()/cycle_mode(), so both reach the
    transport through this one subscription - same shape as reasoning
    level's own projection above."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()

    await bus.publish(
        ResponseModeChanged,
        ResponseModeChanged(mode=ResponseMode.VOICE, source="HOTKEY"),
    )
    assert server.state.snapshot()["response_mode"] == {"mode": "voice"}

    await bus.publish(
        ResponseModeChanged,
        ResponseModeChanged(mode=ResponseMode.TEXT_VOICE, source="UI"),
    )
    assert server.state.snapshot()["response_mode"] == {"mode": "text_voice"}


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


def test_max_audio_attachment_clips_defaults_to_the_attachment_policy_cap():
    server = UiTransportServer(EventBus(), _FakeControlApi())

    assert server._max_audio_attachment_seconds == MAX_CLIPS_PER_FILE * MAX_CLIP_SECONDS


def test_max_audio_attachment_clips_is_configurable():
    server = UiTransportServer(
        EventBus(), _FakeControlApi(), max_audio_attachment_clips=7
    )

    assert server._max_audio_attachment_seconds == 7 * MAX_CLIP_SECONDS


def test_debug_is_off_by_default_in_the_snapshot():
    state = UiStateStore()

    assert state.snapshot()["debug"] == {"enabled": False}


def test_debug_flag_reaches_the_snapshot_when_the_run_is_started_with_it():
    """The state snapshot is what a reconnecting client (or a second one)
    reads, so the banner must survive that without depending on having
    been present for the original announce_debug_mode() call."""
    state = UiStateStore(debug=True)

    assert state.snapshot()["debug"] == {"enabled": True}


def test_set_mcp_enabled_control_requires_boolean_target():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("set_mcp_enabled", {"enabled": True})

    assert control_api.calls == [("set_mcp_enabled", "True")]
    with pytest.raises(ProtocolError, match="arguments.enabled"):
        server._dispatch_control("set_mcp_enabled", {"enabled": "true"})


def test_set_tts_enabled_control_requires_boolean_target():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("set_tts_enabled", {"enabled": False})

    assert control_api.calls == [("set_tts_enabled", "False")]
    with pytest.raises(ProtocolError, match="arguments.enabled"):
        server._dispatch_control("set_tts_enabled", {"enabled": "false"})


def test_set_solo_session_enabled_control_requires_boolean_target():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("set_solo_session_enabled", {"enabled": True})

    assert control_api.calls == [("set_solo_session_enabled", "True")]
    with pytest.raises(ProtocolError, match="arguments.enabled"):
        server._dispatch_control("set_solo_session_enabled", {"enabled": "true"})


def test_tts_enabled_defaults_to_true_in_the_snapshot():
    state = UiStateStore()

    assert state.snapshot()["tts"] == {"enabled": True}


def test_tts_enabled_seeds_from_constructor():
    state = UiStateStore(tts_enabled=False)

    assert state.snapshot()["tts"] == {"enabled": False}


async def test_tts_speech_enabled_changed_projects_into_the_tts_state():
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()

    await bus.publish(TtsSpeechEnabledChanged, TtsSpeechEnabledChanged(enabled=False))

    assert server.state.snapshot()["tts"] == {"enabled": False}


def test_solo_session_enabled_defaults_to_false_in_the_snapshot():
    state = UiStateStore()

    assert state.snapshot()["solo_session"] == {"enabled": False}


def test_solo_session_enabled_seeds_from_constructor():
    state = UiStateStore(solo_session_enabled=True)

    assert state.snapshot()["solo_session"] == {"enabled": True}


async def test_solo_session_changed_projects_into_the_solo_session_state():
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()

    await bus.publish(SoloSessionChanged, SoloSessionChanged(enabled=True))

    assert server.state.snapshot()["solo_session"] == {"enabled": True}


def test_set_tool_enabled_control_requires_name_and_boolean_target():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("set_tool_enabled", {"name": "remember", "enabled": False})

    assert control_api.calls == [("set_tool_enabled", "remember", "False")]
    with pytest.raises(ProtocolError, match="set_tool_enabled"):
        server._dispatch_control("set_tool_enabled", {"name": "", "enabled": True})
    with pytest.raises(ProtocolError, match="set_tool_enabled"):
        server._dispatch_control("set_tool_enabled", {"name": "remember"})


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
        "microphone_host_api": "MME",
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
        "tts_enabled": False,
    }


def test_save_config_selection_parses_iteration_2_arguments():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control("save_config_selection", _full_config_arguments())

    assert control_api.config_kwargs["microphone_host_api"] == "MME"
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
    assert control_api.config_kwargs["tts_enabled"] is False


def test_save_config_selection_parses_the_response_mode_argument():
    """Task 3b: response_mode joins the batch Settings form as an ordinary
    restart-to-apply field; the transport passes the form's chosen value
    through as a string - value semantics belong to
    validate_selection() behind the control API, exactly like ui_language."""
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control(
        "save_config_selection",
        {"model": "demo", "microphone": "mic-1", "response_mode": "voice"},
    )

    assert control_api.config_kwargs["response_mode"] == "voice"


def test_save_config_selection_rejects_a_non_string_response_mode():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    with pytest.raises(ProtocolError, match="response_mode"):
        server._dispatch_control(
            "save_config_selection",
            {"model": "demo", "microphone": "mic-1", "response_mode": 3},
        )

    assert control_api.calls == []


def test_save_config_selection_without_response_mode_passes_none():
    """An older front-end that omits the field entirely must reach
    write_ui_config as None, which omits the [response] section - a
    previously persisted mode (or config.toml's default) survives an
    unrelated Apply instead of being reset to text (Codex review finding,
    task 3b)."""
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)

    server._dispatch_control(
        "save_config_selection", {"model": "demo", "microphone": "mic-1"}
    )

    assert control_api.config_kwargs["response_mode"] is None


def test_save_config_selection_rejects_non_boolean_tts_enabled():
    control_api = _FakeControlApi()
    server = UiTransportServer(EventBus(), control_api)
    arguments = _full_config_arguments()
    arguments["tts_enabled"] = "false"

    with pytest.raises(ProtocolError, match="tts_enabled"):
        server._dispatch_control("save_config_selection", arguments)

    assert control_api.calls == []


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
        # Absent host API stays "", the pre-host_api meaning: resolve by
        # name and fail if that is ambiguous, never pick a copy.
        "microphone_host_api": "",
        "ui_language": None,
        "vad": None,
        "tts_routes": None,
        "tts_enabled": None,
        "response_mode": None,
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
    assert values["response_mode"] == "text"
    assert values["response_mode_options"] == ["text", "voice", "text_voice"]
    assert values["vad"]["threshold"] == 0.5
    assert values["tts"]["enabled"] is True
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
        journal_history_service=_rebuilt_history_service(bus, store, search_index),
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
                    "folder_path": str(store.root / session_id),
                },
                {
                    "id": later_session_id,
                    "start_timestamp": "2026-07-17T09:00:00+01:00",
                    "end_timestamp": "2026-07-17T09:00:01+01:00",
                    "title": "reactor check",
                    "folder_path": str(store.root / later_session_id),
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
            ] == [
                (later_session_id, 0, "[reactor] check"),
                (later_session_id, 1, "The [reactor] telemetry is nominal."),
            ]

            user_search = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/search"
                "?token=valid-token&query=real-topic",
            )
            assert [
                (hit["session_id"], hit["event_position"], hit["snippet"])
                for hit in user_search["hits"]
            ] == [(session_id, 2, "the [real] [topic] after voice")]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_search_rejects_limit_over_history_cap(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    search_index = JournalSearchIndex(store, tmp_path)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_search_index=search_index,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.get(
                f"http://127.0.0.1:{info.port}/api/journal/search"
                f"?token=valid-token&query=relay&limit={HISTORY_SEARCH_MAX_RESULTS + 1}"
            )

            assert response.status == 400
            assert await response.text() == (
                f"limit must be at most {HISTORY_SEARCH_MAX_RESULTS}"
            )
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
async def test_journal_input_endpoint_maps_structured_submit_results() -> None:
    for reason, expected in [
        (TextSubmissionReason.ACCEPTED, {"status": "accepted", "reason": "accepted"}),
        (
            TextSubmissionReason.BUSY,
            {"status": "rejected", "reason": "busy", "max_chars": 20},
        ),
        (
            TextSubmissionReason.EMPTY,
            {"status": "rejected", "reason": "empty", "max_chars": 20},
        ),
        (
            TextSubmissionReason.OVER_LIMIT,
            {"status": "rejected", "reason": "over_limit", "max_chars": 20},
        ),
    ]:
        submitter = _FakeTextSubmitter(reason)
        server = UiTransportServer(
            EventBus(),
            _FakeControlApi(),
            token_factory=lambda: "valid-token",
            journal_text_submitter=submitter,
        )
        info = await server.start()
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                    json={"text": "typed from dock"},
                )
                assert response.status == 200
                assert await response.json() == expected
                assert submitter.calls == ["typed from dock"]
        finally:
            await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_reuses_auth_and_rejects_bad_payload() -> None:
    submitter = _FakeTextSubmitter(TextSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_text_submitter=submitter,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            missing_token = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input",
                json={"text": "typed"},
            )
            bad_payload = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                json={"text": 5},
            )
            assert missing_token.status == 401
            assert bad_payload.status == 400
            assert submitter.calls == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_accepts_mixed_attachment_upload() -> None:
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field("text", "look at these")
        form.add_field(
            "files",
            b"\x89PNG\r\n\x1a\nimage-bytes",
            filename="photo.png",
            content_type="image/png",
        )
        form.add_field(
            "files",
            b"ignored",
            filename="manual.pdf",
            content_type="application/pdf",
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            assert response.status == 200
            payload = await response.json()
            assert [file["filename"] for file in payload["files"]] == [
                "photo.png",
                "manual.pdf",
            ]
            assert payload == {
                "status": "accepted",
                "reason": "accepted",
                "files": [
                    {
                        "filename": "photo.png",
                        "status": "accepted",
                        "class": "image",
                        "warnings": [],
                    },
                    {
                        "filename": "manual.pdf",
                        "status": "rejected",
                        "class": None,
                        "warnings": [],
                        "reason": (
                            "manual.pdf: unsupported file type (.pdf). Supported: "
                            "csv, jpeg, jpg, json, log, md, mp3, png, txt, wav."
                        ),
                    },
                ],
            }
        [(typed_text, plan)] = attachment_submitter.calls
        assert typed_text == "look at these"
        assert [item.filename for item in plan.items] == ["photo.png", "manual.pdf"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_marks_and_persists_selected_upload() -> None:
    attachment_submitter = _FakeAttachmentSubmitter(
        AttachmentSubmissionReason.ACCEPTED,
        persisted_files=(
            PersistedFileOutcome("photo.png", storage_name="photo-abcd.png", bytes=11),
        ),
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field("text", "keep the photo")
        form.add_field("persist", "[0]")
        form.add_field(
            "files",
            b"\x89PNG\r\n\x1a\nimage-bytes",
            filename="photo.png",
            content_type="image/png",
        )
        form.add_field(
            "files", b"hello", filename="notes.txt", content_type="text/plain"
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            payload = await response.json()
        [persistent] = attachment_submitter.persistent_uploads
        assert [upload.filename for upload in persistent] == ["photo.png"]
        assert persistent[0].data == b"\x89PNG\r\n\x1a\nimage-bytes"
        assert payload["files"][0]["persistent"] == {
            "status": "saved",
            "storage_name": "photo-abcd.png",
            "bytes": 11,
        }
        assert "persistent" not in payload["files"][1]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_reports_persistent_rejection() -> None:
    attachment_submitter = _FakeAttachmentSubmitter(
        AttachmentSubmissionReason.ACCEPTED,
        persisted_files=(PersistedFileOutcome("doc.md", error="no active session"),),
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field("persist", "[0]")
        form.add_field("files", b"body", filename="doc.md", content_type="text/plain")
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            payload = await response.json()
        assert payload["files"][0]["persistent"] == {
            "status": "rejected",
            "reason": "no active session",
        }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_does_not_persist_a_rejected_upload() -> None:
    # A marked file the planner rejects (unsupported type here, but the same
    # gate covers oversize/wrong-MIME/empty) is never written: it is not handed
    # to the submitter and is reported persistent-rejected.
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field("persist", "[0]")
        form.add_field(
            "files", b"ignored", filename="manual.pdf", content_type="application/pdf"
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            payload = await response.json()
        assert attachment_submitter.persistent_uploads == [()]
        assert payload["files"][0]["status"] == "rejected"
        assert payload["files"][0]["persistent"] == {
            "status": "rejected",
            "reason": "attachment was rejected; not saved",
        }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_ignores_out_of_range_and_bad_persist() -> None:
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        for persist_value in ("[5]", "not-json", '{"a":1}'):
            attachment_submitter.persistent_uploads.clear()
            form = aiohttp.FormData()
            form.add_field("persist", persist_value)
            form.add_field(
                "files", b"body", filename="doc.md", content_type="text/plain"
            )
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                    data=form,
                )
                payload = await response.json()
            assert attachment_submitter.persistent_uploads == [()]
            assert "persistent" not in payload["files"][0]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_never_trusts_uploaded_filename_paths() -> None:
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field(
            "files",
            b"notes",
            filename="..\\..\\memory.txt",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            assert response.status == 200
            assert await response.json() == {
                "status": "accepted",
                "reason": "accepted",
                "files": [
                    {
                        "filename": "memory.txt",
                        "status": "accepted",
                        "class": "text",
                        "warnings": [],
                    }
                ],
            }
        [(_typed_text, plan)] = attachment_submitter.calls
        assert [item.filename for item in plan.items] == ["memory.txt"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_rejects_attachment_when_turn_has_no_content() -> (
    None
):
    attachment_submitter = _FakeAttachmentSubmitter(
        AttachmentSubmissionReason.NO_ACCEPTED_CONTENT
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field(
            "files",
            b"ignored",
            filename="manual.pdf",
            content_type="application/pdf",
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            assert response.status == 200
            assert await response.json() == {
                "status": "rejected",
                "reason": "no_accepted_content",
                "files": [
                    {
                        "filename": "manual.pdf",
                        "status": "rejected",
                        "class": None,
                        "warnings": [],
                        "reason": (
                            "manual.pdf: unsupported file type (.pdf). Supported: "
                            "csv, jpeg, jpg, json, log, md, mp3, png, txt, wav."
                        ),
                    }
                ],
            }
        assert len(attachment_submitter.calls) == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_rejects_oversize_attachment_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.ui.transport as transport_module

    monkeypatch.setattr(transport_module, "MAX_TOTAL_UPLOAD_BYTES_PER_TURN", 8)
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field(
            "files",
            b"\x89PNG\r\n\x1a\nextra",
            filename="photo.png",
            content_type="image/png",
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            assert response.status == 413
            assert await response.json() == {
                "status": "rejected",
                "reason": "request_too_large",
                "actual_bytes": 13,
                "max_bytes": 8,
                "files": [],
            }
        assert attachment_submitter.calls == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_rejects_files_over_attachment_count_limit() -> (
    None
):
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        for index in range(5):
            form.add_field(
                "files",
                b"\x89PNG\r\n\x1a\nimage-bytes",
                filename=f"photo-{index}.png",
                content_type="image/png",
            )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            assert response.status == 200
            payload = await response.json()
            assert payload["status"] == "accepted"
            assert [file["status"] for file in payload["files"]] == [
                "accepted",
                "accepted",
                "accepted",
                "accepted",
                "rejected",
            ]
            assert payload["files"][-1] == {
                "filename": "photo-4.png",
                "status": "rejected",
                "class": None,
                "warnings": [],
                "reason": "photo-4.png: turn already has the maximum of 4 attachments.",
            }
        [(_typed_text, plan)] = attachment_submitter.calls
        assert [item.filename for item in plan.items] == [
            "photo-0.png",
            "photo-1.png",
            "photo-2.png",
            "photo-3.png",
        ]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_does_not_count_typed_text_against_file_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.ui.transport as transport_module

    monkeypatch.setattr(transport_module, "MAX_TOTAL_UPLOAD_BYTES_PER_TURN", 8)
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field("text", "typed text is not an attachment byte budget")
        form.add_field(
            "files",
            b"\x89PNG\r\n\x1a\n",
            filename="photo.png",
            content_type="image/png",
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            assert response.status == 200
            assert (await response.json())["status"] == "accepted"
        [(typed_text, _plan)] = attachment_submitter.calls
        assert typed_text == "typed text is not an attachment byte budget"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_maps_outer_request_size_limit_to_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.ui.transport as transport_module

    monkeypatch.setattr(transport_module, "MAX_JOURNAL_UPLOAD_REQUEST_BYTES", 8)
    submitter = _FakeTextSubmitter(TextSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_text_submitter=submitter,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                json={"text": "this JSON request body exceeds eight bytes"},
            )
            payload = await response.json()
            assert response.status == 413
            assert payload["status"] == "rejected"
            assert payload["reason"] == "request_too_large"
            assert payload["actual_bytes"] > 8
            assert payload["max_bytes"] == 8
            assert payload["files"] == []
        assert submitter.calls == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_keeps_text_only_multipart_response_shape() -> (
    None
):
    submitter = _FakeTextSubmitter(TextSubmissionReason.ACCEPTED)
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_text_submitter=submitter,
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field("text", "typed only", content_type="text/plain")
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=form,
            )
            assert response.status == 200
            assert await response.json() == {
                "status": "accepted",
                "reason": "accepted",
                "files": [],
            }
        assert submitter.calls == ["typed only"]
        assert attachment_submitter.calls == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_input_endpoint_reuses_auth_for_attachment_upload() -> None:
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_attachment_submitter=attachment_submitter,
    )
    info = await server.start()
    try:
        form = aiohttp.FormData()
        form.add_field(
            "files",
            b"\x89PNG\r\n\x1a\nimage-bytes",
            filename="photo.png",
            content_type="image/png",
        )
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input",
                data=form,
            )
            assert response.status == 401
        assert attachment_submitter.calls == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_new_context_endpoint_maps_success_and_busy() -> None:
    for result, expected_status, expected_payload in [
        (
            NewContextResult(
                NewContextReason.ACCEPTED,
                session_id="20260719-100000-ab12",
                provenance_text="Новый пустой контекст создан пользователем.",
            ),
            200,
            {
                "status": "ok",
                "session_id": "20260719-100000-ab12",
                "provenance": "Новый пустой контекст создан пользователем.",
            },
        ),
        (
            NewContextResult(NewContextReason.BUSY),
            409,
            {"status": "rejected", "reason": "busy"},
        ),
    ]:
        handler = _FakeNewContextHandler(result)
        server = UiTransportServer(
            EventBus(),
            _FakeControlApi(),
            token_factory=lambda: "valid-token",
            journal_new_context_handler=handler,
        )
        info = await server.start()
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"http://127.0.0.1:{info.port}/api/journal/context/new"
                    "?token=valid-token"
                )
                assert response.status == expected_status
                assert await response.json() == expected_payload
                assert handler.calls == 1
        finally:
            await server.stop()


@pytest.mark.asyncio
async def test_journal_new_context_endpoint_is_suppressed_while_hidden() -> None:
    handler = _FakeNewContextHandler(
        NewContextResult(
            NewContextReason.ACCEPTED,
            session_id="20260719-100000-ab12",
            provenance_text="Новый пустой контекст создан пользователем.",
        )
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        state=UiStateStore(visibility_mode=VisibilityMode.HIDDEN),
        token_factory=lambda: "valid-token",
        journal_new_context_handler=handler,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/context/new"
                "?token=valid-token"
            )
            assert response.status == 200
            assert await response.json() == {"status": "hidden"}
            assert handler.calls == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_fork_endpoint_reads_source_and_maps_success(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    source_session_id = "20260718-150000-ab12"
    store.append(
        _journal_event(
            session_id=source_session_id,
            timestamp="2026-07-18T15:00:00+01:00",
            source="dock",
            role="user",
            text="source turn",
        )
    )
    store.append(
        _journal_event(
            session_id=source_session_id,
            timestamp="2026-07-18T15:01:00+01:00",
            source="assistant",
            role="assistant",
            text="source answer",
        )
    )
    fork_handler = _FakeJournalForkHandler(
        ForkSessionResult(
            ForkSessionReason.ACCEPTED,
            new_session_id="20260719-100000-cd34",
            drop_report=ForkSeedDropReport(
                dropped_turns=1, skipped_events=0, truncated=True
            ),
            provenance_text="continued",
            max_chars=25,
        )
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_fork_handler=fork_handler,
        journal_fork_seed_max_chars=25,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                f"{source_session_id}/fork?token=valid-token"
            )
            assert response.status == 200
            assert await response.json() == {
                "status": "ok",
                "session_id": "20260719-100000-cd34",
                "continued_from": source_session_id,
                "provenance": "continued",
                "seed": {
                    "dropped_turns": 1,
                    "skipped_events": 0,
                    "excluded_events": 0,
                    "truncated": True,
                    "max_chars": 25,
                },
            }
            assert len(fork_handler.calls) == 1
            assert fork_handler.calls[0]["source_session_id"] == source_session_id
            assert fork_handler.calls[0]["source_end_timestamp"] == (
                "2026-07-18T15:01:00+01:00"
            )
            assert fork_handler.calls[0]["seed_budget_chars"] == 25
            assert [event.text for event in fork_handler.calls[0]["replay"].events] == [
                "source turn",
                "source answer",
            ]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_fork_endpoint_reads_only_the_requested_session(
    tmp_path: Path,
) -> None:
    store = _NoListJournalStore(tmp_path)
    source_session_id = "20260718-150000-ab12"
    store.append(
        _journal_event(
            session_id=source_session_id,
            timestamp="2026-07-18T15:00:00+01:00",
            source="dock",
            role="user",
            text="source turn",
        )
    )
    fork_handler = _FakeJournalForkHandler(
        ForkSessionResult(
            ForkSessionReason.ACCEPTED,
            new_session_id="20260719-100000-cd34",
            drop_report=ForkSeedDropReport(
                dropped_turns=0, skipped_events=0, truncated=False
            ),
            provenance_text="continued",
            max_chars=DEFAULT_FORK_SEED_MAX_CHARS,
        )
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_fork_handler=fork_handler,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                f"{source_session_id}/fork?token=valid-token"
            )
            assert response.status == 200
            assert fork_handler.calls[0]["seed_budget_chars"] == (
                DEFAULT_FORK_SEED_MAX_CHARS
            )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_fork_endpoint_maps_rejections_and_unknown_session(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    source_session_id = "20260718-150000-ab12"
    store.append(
        _journal_event(
            session_id=source_session_id,
            timestamp="2026-07-18T15:00:00+01:00",
            source="dock",
            role="user",
            text="source turn",
        )
    )
    for result, expected_status, expected_payload in [
        (
            ForkSessionResult(ForkSessionReason.BUSY),
            409,
            {"status": "rejected", "reason": "busy"},
        ),
        (
            ForkSessionResult(
                ForkSessionReason.OVERSIZE_TURN,
                oversize_turn_chars=200,
                max_chars=25,
            ),
            409,
            {
                "status": "rejected",
                "reason": "oversize_turn",
                "turn_chars": 200,
                "max_chars": 25,
            },
        ),
    ]:
        fork_handler = _FakeJournalForkHandler(result)
        server = UiTransportServer(
            EventBus(),
            _FakeControlApi(),
            token_factory=lambda: "valid-token",
            journal_store=store,
            journal_fork_handler=fork_handler,
            journal_fork_seed_max_chars=25,
        )
        info = await server.start()
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                    f"{source_session_id}/fork?token=valid-token"
                )
                assert response.status == expected_status
                assert await response.json() == expected_payload
        finally:
            await server.stop()

    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_fork_handler=_FakeJournalForkHandler(
            ForkSessionResult(ForkSessionReason.ACCEPTED)
        ),
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                "20260718-150000-missing/fork?token=valid-token"
            )
            assert response.status == 404
            assert await response.json() == {
                "status": "rejected",
                "reason": "unknown_session",
            }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_journal_usage_and_delete_api_keep_search_consistent(
    tmp_path: Path,
) -> None:
    store = JournalStore(tmp_path)
    deleted_session = "20260716-153000-ab12"
    active_session = "20260717-153000-cd34"
    store.append(
        _journal_event(
            session_id=deleted_session,
            timestamp="2026-07-16T15:30:00+01:00",
            source="assistant",
            role="assistant",
            text="delete me answer",
        )
    )
    store.write_media(deleted_session, "clip.wav", b"12345")
    store.append(
        _journal_event(
            session_id=active_session,
            timestamp="2026-07-17T15:30:00+01:00",
            source="assistant",
            role="assistant",
            text="keep me answer",
        )
    )
    search_index = JournalSearchIndex(store, tmp_path)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_history_service=_rebuilt_history_service(
            EventBus(), store, search_index
        ),
        journal_active_session_id=lambda: active_session,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            usage = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/usage?token=valid-token",
            )
            assert usage["status"] == "ok"
            assert usage["total_bytes"] > 5
            assert {item["id"] for item in usage["sessions"]} == {
                deleted_session,
                active_session,
            }

            active_delete = await session.delete(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                f"{active_session}?token=valid-token"
            )
            assert active_delete.status == 409
            assert await active_delete.json() == {
                "status": "rejected",
                "reason": "active_session",
            }

            deleted = await session.delete(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                f"{deleted_session}?token=valid-token"
            )
            assert deleted.status == 200
            assert await deleted.json() == {
                "status": "ok",
                "deleted_session_id": deleted_session,
            }
            assert not (tmp_path / deleted_session).exists()
            assert [hit.session_id for hit in search_index.search("answer")] == [
                active_session
            ]

            missing = await session.delete(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                "20260718-153000-missing?token=valid-token"
            )
            assert missing.status == 404
            assert await missing.json() == {
                "status": "rejected",
                "reason": "not_found",
            }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_memory_file_api_reads_missing_and_round_trips_utf8(
    tmp_path: Path,
) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(
            MemorySettings(root=str(tmp_path), memory_max_chars=100)
        )
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        memory_file_repository=repository,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            missing = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/memory/files/memory"
                "?token=valid-token",
            )
            assert missing == {
                "status": "ok",
                "file": "memory",
                "content": "",
                "chars": 0,
                "max_chars": 100,
            }

            written_response = await session.put(
                f"http://127.0.0.1:{info.port}/api/memory/files/memory"
                "?token=valid-token",
                json={"content": "Память: локально."},
            )
            assert written_response.status == 200
            written = await written_response.json()
            assert written["content"] == "Память: локально."
            assert written["chars"] == len("Память: локально.")

            reread = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/memory/files/memory"
                "?token=valid-token",
            )
            assert reread == written
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_memory_file_api_auth_hidden_over_cap_and_invalid_identifier(
    tmp_path: Path,
) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path), memory_max_chars=3))
    )
    hidden_server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        state=UiStateStore(visibility_mode=VisibilityMode.HIDDEN),
        token_factory=lambda: "valid-token",
        memory_file_repository=repository,
    )
    hidden_info = await hidden_server.start()
    try:
        async with aiohttp.ClientSession() as session:
            hidden_get = await _get_json(
                session,
                f"http://127.0.0.1:{hidden_info.port}/api/memory/files/memory"
                "?token=valid-token",
            )
            assert hidden_get == {"status": "hidden"}
            hidden_put = await session.put(
                f"http://127.0.0.1:{hidden_info.port}/api/memory/files/memory"
                "?token=valid-token",
                json={"content": "new"},
            )
            assert hidden_put.status == 200
            assert await hidden_put.json() == {"status": "hidden"}
    finally:
        await hidden_server.stop()

    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        memory_file_repository=repository,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            missing_token = await session.get(
                f"http://127.0.0.1:{info.port}/api/memory/files/memory"
            )
            assert missing_token.status == 401

            invalid = await session.get(
                f"http://127.0.0.1:{info.port}/api/memory/files/..%2Fsecret"
                "?token=valid-token",
            )
            assert invalid.status == 400
            assert await invalid.json() == {
                "status": "rejected",
                "reason": "invalid_file",
            }

            bad_payload = await session.put(
                f"http://127.0.0.1:{info.port}/api/memory/files/memory"
                "?token=valid-token",
                json={"content": "abcd"},
            )
            assert bad_payload.status == 413
            assert await bad_payload.json() == {
                "status": "rejected",
                "reason": "over_limit",
                "chars": 4,
                "max_chars": 3,
            }
            assert repository.read(MemoryFileId.MEMORY).content == ""
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
    submitter = _FakeTextSubmitter(TextSubmissionReason.ACCEPTED)
    attachment_submitter = _FakeAttachmentSubmitter(AttachmentSubmissionReason.ACCEPTED)
    fork_handler = _FakeJournalForkHandler(
        ForkSessionResult(ForkSessionReason.ACCEPTED)
    )
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        state=state,
        token_factory=lambda: "valid-token",
        journal_store=store,
        journal_search_index=JournalSearchIndex(store, tmp_path),
        journal_text_submitter=submitter,
        journal_attachment_submitter=attachment_submitter,
        journal_fork_handler=fork_handler,
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
                    f"http://127.0.0.1:{info.port}/api/journal/usage?token=valid-token",
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
            hidden_input = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                json={"text": "must not leave transport"},
            )
            assert hidden_input.status == 200
            assert await hidden_input.json() == {"status": "hidden"}
            assert submitter.calls == []
            hidden_form = aiohttp.FormData()
            hidden_form.add_field(
                "files",
                b"\x89PNG\r\n\x1a\nimage-bytes",
                filename="photo.png",
                content_type="image/png",
            )
            hidden_attachment_input = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/input?token=valid-token",
                data=hidden_form,
            )
            assert hidden_attachment_input.status == 200
            assert await hidden_attachment_input.json() == {"status": "hidden"}
            assert attachment_submitter.calls == []
            hidden_fork = await session.post(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                f"{event.session_id}/fork?token=valid-token"
            )
            assert hidden_fork.status == 200
            assert await hidden_fork.json() == {"status": "hidden"}
            assert fork_handler.calls == []
            hidden_delete = await session.delete(
                f"http://127.0.0.1:{info.port}/api/journal/sessions/"
                f"{event.session_id}?token=valid-token"
            )
            assert hidden_delete.status == 200
            assert await hidden_delete.json() == {"status": "hidden"}

            async with session.ws_connect(info.websocket_url) as websocket:
                await websocket.send_json(hello_message("status-console", ["state"]))
                await websocket.receive_json()
                await websocket.receive_json()

                await bus.publish(
                    JournalEventAppended,
                    JournalEventAppended(
                        reference=JournalEventRef(event.session_id, 0),
                        event=event,
                    ),
                )
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
    lifecycle = _history_lifecycle(bus, search_index)
    await lifecycle.start()
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_history_service=JournalHistoryService(store, lifecycle, search_index),
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
            await lifecycle.wait_for_idle()
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
        await lifecycle.close()
        await server.stop()


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict:
    response = await session.get(url)
    assert response.status == 200
    return await response.json()


async def _post_json(session: aiohttp.ClientSession, url: str) -> dict:
    response = await session.post(url)
    assert response.status == 200
    return await response.json()


async def test_reply_replay_route_invokes_handler_and_returns_outcome():
    captured: list[JournalEventRef] = []

    async def handler(reference: JournalEventRef) -> str:
        captured.append(reference)
        return "started"

    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_reply_replay_handler=handler,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            result = await _post_json(
                session,
                f"http://127.0.0.1:{info.port}"
                "/api/journal/replies/20260826-101500-abc/2/replay"
                "?token=valid-token",
            )
        assert result == {"outcome": "started"}
    finally:
        await server.stop()
    assert captured == [JournalEventRef("20260826-101500-abc", 2)]


async def test_replay_progress_broadcasts_now_playing_then_clear_deltas():
    bus = EventBus()
    server = UiTransportServer(
        bus, _FakeControlApi(), token_factory=lambda: "valid-token"
    )
    info = await server.start()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.ws_connect(info.websocket_url) as websocket,
        ):
            await websocket.send_json(hello_message("status-console", ["state"]))
            await websocket.receive_json()  # hello_ack
            await websocket.receive_json()  # snapshot

            await bus.publish(
                ReplayProgress,
                ReplayProgress(JournalEventRef("20260826-101500-abc", 3)),
            )
            playing = await websocket.receive_json()
            assert playing["payload"]["key"] == "replay_progress"
            assert playing["payload"]["value"] == {
                "session_id": "20260826-101500-abc",
                "event_position": 3,
            }

            await bus.publish(ReplayProgress, ReplayProgress(None))
            cleared = await websocket.receive_json()
            assert cleared["payload"]["key"] == "replay_progress"
            assert cleared["payload"]["value"] is None
    finally:
        await server.stop()


async def test_reply_sequence_route_invokes_handler_and_returns_outcome():
    captured: list[JournalEventRef] = []

    async def handler(reference: JournalEventRef) -> str:
        captured.append(reference)
        return "started"

    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_reply_sequence_handler=handler,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            result = await _post_json(
                session,
                f"http://127.0.0.1:{info.port}"
                "/api/journal/replies/20260826-101500-abc/2/replay-sequence"
                "?token=valid-token",
            )
        assert result == {"outcome": "started"}
    finally:
        await server.stop()
    assert captured == [JournalEventRef("20260826-101500-abc", 2)]


async def test_reply_replay_stop_route_calls_stop_handler():
    calls: list[bool] = []

    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_reply_replay_stop_handler=lambda: calls.append(True),
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            result = await _post_json(
                session,
                f"http://127.0.0.1:{info.port}"
                "/api/journal/replies/replay/stop?token=valid-token",
            )
        assert result == {"stopped": True}
    finally:
        await server.stop()
    assert calls == [True]


async def test_reply_replay_pause_and_resume_routes_call_their_handlers():
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_reply_replay_pause_handler=lambda: True,
        journal_reply_replay_resume_handler=lambda: False,
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            paused = await _post_json(
                session,
                f"http://127.0.0.1:{info.port}"
                "/api/journal/replies/replay/pause?token=valid-token",
            )
            resumed = await _post_json(
                session,
                f"http://127.0.0.1:{info.port}"
                "/api/journal/replies/replay/resume?token=valid-token",
            )
        assert paused == {"paused": True}
        assert resumed == {"resumed": False}
    finally:
        await server.stop()


def _rebuilt_history_service(
    bus: EventBus, store: JournalStore, search_index: JournalSearchIndex
) -> JournalHistoryService:
    lifecycle = _history_lifecycle(bus, search_index)
    search_index.repository.rebuild()
    return JournalHistoryService(store, lifecycle, search_index)


@pytest.mark.asyncio
async def test_journal_search_endpoint_labels_locator_hits_distinctly(
    tmp_path: Path,
) -> None:
    # story-v1.9.1 task 4: a derivative-only phrase reaches the Journal UI as
    # a DISTINCTY labeled locator hit with hydrated canonical text; the
    # canonical hit kind is unchanged for canonical queries.
    bus = EventBus()
    store = JournalStore(tmp_path)
    session_id = "20260716-153000-ab12"
    store.append(
        JournalEvent(
            session_id=session_id,
            timestamp="2026-07-16T15:30:00+01:00",
            source="assistant",
            role="assistant",
            text="Канонический ответ про насос.",
            media=[],
            transcript=None,
            metadata={"spoken_derivative": "напоминаю, реле перегрелось из-за пыли"},
        )
    )
    search_index = JournalSearchIndex(store, tmp_path)
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_history_service=_rebuilt_history_service(bus, store, search_index),
    )
    info = await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            locator_search = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/search"
                "?token=valid-token&query=перегрелось",
            )
            assert locator_search["status"] == "ok"
            # Locator matches travel in their own group, never among the
            # canonical hits (no ranking blend).
            assert locator_search["hits"] == []
            [locator_hit] = locator_search["locator_hits"]
            assert locator_hit["kind"] == "locator"
            assert (locator_hit["session_id"], locator_hit["event_position"]) == (
                session_id,
                0,
            )
            assert locator_hit["canonical_text"] == "Канонический ответ про насос."
            assert locator_hit["snippet"] != locator_hit["canonical_text"]
            assert "из-за пыли" in locator_hit["snippet"]

            canonical_search = await _get_json(
                session,
                f"http://127.0.0.1:{info.port}/api/journal/search"
                "?token=valid-token&query=канонический",
            )
            [canonical_hit] = canonical_search["hits"]
            assert canonical_hit["kind"] == "canonical"
    finally:
        await server.stop()


def _history_lifecycle(
    bus: EventBus, search_index: JournalSearchIndex
) -> HistoryProjectionLifecycle:
    semantic_projection = UnavailableSemanticHistoryProjection()
    return HistoryProjectionLifecycle(
        bus,
        projections=(CorpusHistoryProjection(search_index.repository),),
        semantic_projection=semantic_projection,
    )


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


_TRANSCRIPT_SESSION = "20260801-120000-ab12"


def _voice_store(tmp_path: Path) -> tuple[JournalStore, TranscriptOverlayRepository]:
    store = JournalStore(tmp_path / "journal")
    store.append(
        _journal_event(
            session_id=_TRANSCRIPT_SESSION,
            timestamp="2026-08-01T12:00:00+01:00",
            source="voice",
            role="user",
            text="",
            media=("utterance.wav",),
        )
    )
    overlays = TranscriptOverlayRepository(
        tmp_path / "derived", JournalStoreEventReferenceResolver(store)
    )
    return store, overlays


class _FakeTranscriptionService:
    def __init__(self, result: TranscriptionResult) -> None:
        self._result = result
        self.calls: list[JournalEventRef] = []

    async def transcribe_event(self, reference: JournalEventRef) -> TranscriptionResult:
        self.calls.append(reference)
        return self._result


@pytest.mark.asyncio
async def test_transcript_api_read_edit_round_trip_and_publishes_change(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    _store, overlays = _voice_store(tmp_path)
    changed: list[JournalEventRef] = []

    async def _capture(event: TranscriptOverlayChanged) -> None:
        changed.append(event.reference)

    bus.subscribe(TranscriptOverlayChanged, _capture)
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_transcript_repository=overlays,
    )
    info = await server.start()
    base = (
        f"http://127.0.0.1:{info.port}/api/journal/transcripts/{_TRANSCRIPT_SESSION}/0"
    )
    try:
        async with aiohttp.ClientSession() as session:
            missing = await _get_json(session, base + "?token=valid-token")
            assert missing["found"] is False
            assert missing["transcript"] is None

            written = await session.put(
                base + "?token=valid-token", json={"text": "секретный код альфа"}
            )
            assert written.status == 200
            payload = await written.json()
            assert payload["found"] is True
            assert payload["transcript"]["text"] == "секретный код альфа"
            assert payload["transcript"]["source"] == "edited"

            reread = await _get_json(session, base + "?token=valid-token")
            assert reread["transcript"]["text"] == "секретный код альфа"
    finally:
        await server.stop()

    assert changed == [JournalEventRef(_TRANSCRIPT_SESSION, 0)]


@pytest.mark.asyncio
async def test_transcript_api_edit_rejections(tmp_path: Path) -> None:
    _store, overlays = _voice_store(tmp_path)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_transcript_repository=overlays,
    )
    info = await server.start()
    base = f"http://127.0.0.1:{info.port}/api/journal/transcripts"
    try:
        async with aiohttp.ClientSession() as session:
            empty = await session.put(
                f"{base}/{_TRANSCRIPT_SESSION}/0?token=valid-token",
                json={"text": ""},
            )
            assert empty.status == 400
            assert (await empty.json())["reason"] == "text_empty"

            too_long = await session.put(
                f"{base}/{_TRANSCRIPT_SESSION}/0?token=valid-token",
                json={"text": "x" * 20001},
            )
            assert too_long.status == 413
            assert (await too_long.json())["reason"] == "text_too_long"

            unknown = await session.put(
                f"{base}/{_TRANSCRIPT_SESSION}/9?token=valid-token",
                json={"text": "no such event"},
            )
            assert unknown.status == 404
            assert (await unknown.json())["reason"] == "unknown_reference"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_transcript_api_hidden_and_token(tmp_path: Path) -> None:
    _store, overlays = _voice_store(tmp_path)
    hidden = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        state=UiStateStore(visibility_mode=VisibilityMode.HIDDEN),
        token_factory=lambda: "valid-token",
        journal_transcript_repository=overlays,
    )
    hidden_info = await hidden.start()
    base = (
        f"http://127.0.0.1:{hidden_info.port}/api/journal/transcripts/"
        f"{_TRANSCRIPT_SESSION}/0"
    )
    try:
        async with aiohttp.ClientSession() as session:
            hidden_get = await _get_json(session, base + "?token=valid-token")
            assert hidden_get == {"status": "hidden"}
            missing_token = await session.get(base)
            assert missing_token.status == 401
    finally:
        await hidden.stop()


@pytest.mark.asyncio
async def test_transcript_generate_endpoint(tmp_path: Path) -> None:
    bus = EventBus()
    _store, overlays = _voice_store(tmp_path)
    reference = JournalEventRef(_TRANSCRIPT_SESSION, 0)
    changed: list[JournalEventRef] = []

    async def _capture(event: TranscriptOverlayChanged) -> None:
        changed.append(event.reference)

    bus.subscribe(TranscriptOverlayChanged, _capture)
    service = _FakeTranscriptionService(
        TranscriptionResult(
            reference,
            TranscriptionOutcome.TRANSCRIBED,
            transcript="сгенерированный текст",
        )
    )
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_transcript_repository=overlays,
        journal_transcription_service=service,
    )
    info = await server.start()
    generate = (
        f"http://127.0.0.1:{info.port}/api/journal/transcripts/"
        f"{_TRANSCRIPT_SESSION}/0/generate?token=valid-token"
    )
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(generate)
            assert response.status == 200
            payload = await response.json()
            assert payload["status"] == "ok"
            assert payload["outcome"] == "transcribed"
            assert payload["transcript"] == "сгенерированный текст"
    finally:
        await server.stop()

    assert service.calls == [reference]
    assert changed == [reference]


@pytest.mark.asyncio
async def test_transcript_generate_reports_no_audio(tmp_path: Path) -> None:
    _store, overlays = _voice_store(tmp_path)
    reference = JournalEventRef(_TRANSCRIPT_SESSION, 0)
    service = _FakeTranscriptionService(
        TranscriptionResult(reference, TranscriptionOutcome.NO_AUDIO_MEDIA)
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_transcript_repository=overlays,
        journal_transcription_service=service,
    )
    info = await server.start()
    generate = (
        f"http://127.0.0.1:{info.port}/api/journal/transcripts/"
        f"{_TRANSCRIPT_SESSION}/0/generate?token=valid-token"
    )
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(generate)
            assert response.status == 409
            assert (await response.json())["reason"] == "no_audio_media"
    finally:
        await server.stop()


_ANNOTATION_SESSION = "20260801-130000-cd34"


def _annotation_store(
    tmp_path: Path,
) -> tuple[JournalStore, AnnotationOverlayRepository]:
    store = JournalStore(tmp_path / "journal")
    for position, role, text in (
        (0, "user", "первое событие"),
        (1, "assistant", "ответ"),
    ):
        store.append(
            _journal_event(
                session_id=_ANNOTATION_SESSION,
                timestamp=f"2026-08-01T13:0{position}:00+01:00",
                source="text",
                role=role,
                text=text,
            )
        )
    overlays = AnnotationOverlayRepository(
        tmp_path / "derived", JournalStoreEventReferenceResolver(store)
    )
    return store, overlays


class _FakeAnnotationGenerationService:
    def __init__(self, result: AnnotationGenerationResult) -> None:
        self._result = result
        self.calls: list[AnnotationTarget] = []

    async def generate_annotation(
        self, target: AnnotationTarget
    ) -> AnnotationGenerationResult:
        self.calls.append(target)
        return self._result


@pytest.mark.asyncio
async def test_annotation_api_list_read_edit_round_trip_and_publishes_change(
    tmp_path: Path,
) -> None:
    bus = EventBus()
    _store, overlays = _annotation_store(tmp_path)
    write = overlays.add_annotation(
        AnnotationTarget(_ANNOTATION_SESSION, 0, 1),
        "исходная заметка",
        author="jarvis",
        source=AnnotationSource.GENERATED,
    )
    annotation_id = write.annotation_id
    assert annotation_id is not None
    changed: list[tuple[str, str]] = []

    async def _capture(event: AnnotationOverlayChanged) -> None:
        changed.append((event.session_id, event.annotation_id))

    bus.subscribe(AnnotationOverlayChanged, _capture)
    server = UiTransportServer(
        bus,
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_annotation_repository=overlays,
    )
    info = await server.start()
    root = f"http://127.0.0.1:{info.port}/api/journal/annotations"
    try:
        async with aiohttp.ClientSession() as session:
            listing = await _get_json(
                session, f"{root}/{_ANNOTATION_SESSION}?token=valid-token"
            )
            assert [item["annotation_id"] for item in listing["annotations"]] == [
                annotation_id
            ]
            annotation = listing["annotations"][0]
            assert annotation["source"] == "generated"
            assert annotation["status"] == "active"
            assert annotation["target"] == {
                "session_id": _ANNOTATION_SESSION,
                "start_position": 0,
                "end_position": 1,
            }

            read = await _get_json(
                session,
                f"{root}/{_ANNOTATION_SESSION}/{annotation_id}?token=valid-token",
            )
            assert read["annotation"]["text"] == "исходная заметка"

            written = await session.put(
                f"{root}/{_ANNOTATION_SESSION}/{annotation_id}?token=valid-token",
                json={"text": "поправленная заметка"},
            )
            assert written.status == 200
            payload = await written.json()
            assert payload["annotation"]["text"] == "поправленная заметка"
            assert payload["annotation"]["source"] == "edited"

            reread = await _get_json(
                session,
                f"{root}/{_ANNOTATION_SESSION}/{annotation_id}?token=valid-token",
            )
            assert reread["annotation"]["text"] == "поправленная заметка"
    finally:
        await server.stop()

    assert changed == [(_ANNOTATION_SESSION, annotation_id)]


@pytest.mark.asyncio
async def test_annotation_api_edit_rejections(tmp_path: Path) -> None:
    _store, overlays = _annotation_store(tmp_path)
    write = overlays.add_annotation(
        AnnotationTarget(_ANNOTATION_SESSION),
        "заметка",
        author="jarvis",
        source=AnnotationSource.GENERATED,
    )
    annotation_id = write.annotation_id
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_annotation_repository=overlays,
    )
    info = await server.start()
    root = f"http://127.0.0.1:{info.port}/api/journal/annotations"
    try:
        async with aiohttp.ClientSession() as session:
            empty = await session.put(
                f"{root}/{_ANNOTATION_SESSION}/{annotation_id}?token=valid-token",
                json={"text": ""},
            )
            assert empty.status == 400
            assert (await empty.json())["reason"] == "text_empty"

            too_long = await session.put(
                f"{root}/{_ANNOTATION_SESSION}/{annotation_id}?token=valid-token",
                json={"text": "x" * 20001},
            )
            assert too_long.status == 413
            assert (await too_long.json())["reason"] == "text_too_long"

            unknown = await session.put(
                f"{root}/{_ANNOTATION_SESSION}/does-not-exist?token=valid-token",
                json={"text": "no such annotation"},
            )
            assert unknown.status == 404

            wrong_session = await session.put(
                f"{root}/20260101-000000-zz99/{annotation_id}?token=valid-token",
                json={"text": "wrong session"},
            )
            assert wrong_session.status == 404
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_annotation_api_hidden_and_token(tmp_path: Path) -> None:
    _store, overlays = _annotation_store(tmp_path)
    hidden = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        state=UiStateStore(visibility_mode=VisibilityMode.HIDDEN),
        token_factory=lambda: "valid-token",
        journal_annotation_repository=overlays,
    )
    hidden_info = await hidden.start()
    base = (
        f"http://127.0.0.1:{hidden_info.port}/api/journal/annotations/"
        f"{_ANNOTATION_SESSION}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            hidden_get = await _get_json(session, base + "?token=valid-token")
            assert hidden_get == {"status": "hidden"}
            missing_token = await session.get(base)
            assert missing_token.status == 401
    finally:
        await hidden.stop()


@pytest.mark.asyncio
async def test_annotation_generate_whole_session_and_range(tmp_path: Path) -> None:
    _store, overlays = _annotation_store(tmp_path)
    service = _FakeAnnotationGenerationService(
        AnnotationGenerationResult(
            AnnotationTarget(_ANNOTATION_SESSION),
            AnnotationGenerationOutcome.GENERATED,
            annotation_id="generated-id",
            annotation="сводка сессии",
        )
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_annotation_repository=overlays,
        journal_annotation_generation_service=service,
    )
    info = await server.start()
    generate = (
        f"http://127.0.0.1:{info.port}/api/journal/annotations/"
        f"{_ANNOTATION_SESSION}/generate?token=valid-token"
    )
    try:
        async with aiohttp.ClientSession() as session:
            whole = await session.post(generate)
            assert whole.status == 200
            whole_payload = await whole.json()
            assert whole_payload["outcome"] == "generated"
            assert whole_payload["annotation_id"] == "generated-id"
            assert whole_payload["target"] == {
                "session_id": _ANNOTATION_SESSION,
                "start_position": None,
                "end_position": None,
            }

            ranged = await session.post(
                generate, json={"start_position": 0, "end_position": 1}
            )
            assert ranged.status == 200
            assert (await ranged.json())["target"] == {
                "session_id": _ANNOTATION_SESSION,
                "start_position": 0,
                "end_position": 1,
            }
    finally:
        await server.stop()

    assert service.calls == [
        AnnotationTarget(_ANNOTATION_SESSION),
        AnnotationTarget(_ANNOTATION_SESSION, 0, 1),
    ]


@pytest.mark.asyncio
async def test_annotation_generate_rejects_reversed_range_without_calling_service(
    tmp_path: Path,
) -> None:
    _store, overlays = _annotation_store(tmp_path)
    service = _FakeAnnotationGenerationService(
        AnnotationGenerationResult(
            AnnotationTarget(_ANNOTATION_SESSION),
            AnnotationGenerationOutcome.GENERATED,
            annotation_id="should-not-happen",
            annotation="unreachable",
        )
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_annotation_repository=overlays,
        journal_annotation_generation_service=service,
    )
    info = await server.start()
    generate = (
        f"http://127.0.0.1:{info.port}/api/journal/annotations/"
        f"{_ANNOTATION_SESSION}/generate?token=valid-token"
    )
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                generate, json={"start_position": 1, "end_position": 0}
            )
            assert response.status == 400
    finally:
        await server.stop()

    assert service.calls == []


@pytest.mark.asyncio
async def test_annotation_generate_reports_failure(tmp_path: Path) -> None:
    _store, overlays = _annotation_store(tmp_path)
    service = _FakeAnnotationGenerationService(
        AnnotationGenerationResult(
            AnnotationTarget(_ANNOTATION_SESSION, 0, 9),
            AnnotationGenerationOutcome.UNKNOWN_RANGE,
            detail="end 9 out of range",
        )
    )
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_annotation_repository=overlays,
        journal_annotation_generation_service=service,
    )
    info = await server.start()
    generate = (
        f"http://127.0.0.1:{info.port}/api/journal/annotations/"
        f"{_ANNOTATION_SESSION}/generate?token=valid-token"
    )
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                generate, json={"start_position": 0, "end_position": 9}
            )
            assert response.status == 404
            body = await response.json()
            assert body["reason"] == "unknown_range"
            assert body["detail"] == "end 9 out of range"
    finally:
        await server.stop()


_CONSOLIDATION_SESSION = "20260801-140000-ef56"


def _consolidation_setup(
    tmp_path: Path,
) -> tuple[
    JournalStore,
    TranscriptOverlayRepository,
    ConsolidationPlanner,
    ConsolidationExecutor,
    ArchiveOverlayRepository,
]:
    # Production shares one root across the raw store and every overlay
    # (app.py); the consolidation API depends on that (media files, the
    # transcript overlay, and the archive record must resolve against the
    # same session directory), unlike the annotation-only fixtures above
    # that can afford a separate "derived" root.
    store = JournalStore(tmp_path)
    resolver = JournalStoreEventReferenceResolver(store)
    transcripts = TranscriptOverlayRepository(tmp_path, resolver)
    annotations = AnnotationOverlayRepository(tmp_path, resolver)
    archive = ArchiveOverlayRepository(tmp_path)
    source = JournalStoreConsolidationSource(store)
    planner = ConsolidationPlanner(source, transcripts, annotations)
    executor = ConsolidationExecutor(planner, source, archive)
    return store, transcripts, planner, executor, archive


@pytest.mark.asyncio
async def test_consolidation_plan_api_reports_transcribed_and_untranscribed_media(
    tmp_path: Path,
) -> None:
    store, transcripts, planner, _executor, _archive = _consolidation_setup(tmp_path)
    store.write_media(_CONSOLIDATION_SESSION, "utterance-0001.wav", b"aaa")
    store.write_media(_CONSOLIDATION_SESSION, "utterance-0002.wav", b"bbbb")
    ref1 = store.append(
        _journal_event(
            session_id=_CONSOLIDATION_SESSION,
            timestamp="2026-08-01T14:00:00+01:00",
            source="voice",
            role="user",
            text="",
            media=("utterance-0001.wav",),
        )
    )
    store.append(
        _journal_event(
            session_id=_CONSOLIDATION_SESSION,
            timestamp="2026-08-01T14:01:00+01:00",
            source="voice",
            role="user",
            text="",
            media=("utterance-0002.wav",),
        )
    )
    transcripts.upsert_transcript(ref1, "первое", TranscriptSource.GENERATED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_consolidation_planner=planner,
    )
    info = await server.start()
    url = (
        f"http://127.0.0.1:{info.port}/api/journal/consolidation/"
        f"{_CONSOLIDATION_SESSION}?token=valid-token"
    )
    try:
        async with aiohttp.ClientSession() as session:
            payload = await _get_json(session, url)
    finally:
        await server.stop()

    plan = payload["plan"]
    assert plan["plan_status"] == "planned"
    assert plan["event_count"] == 2
    assert plan["removable_count"] == 1
    items = {item["media"]: item for item in plan["media_items"]}
    assert items["utterance-0001.wav"]["action"] == "remove"
    assert items["utterance-0001.wav"]["reason"] == "transcribed"
    assert items["utterance-0002.wav"]["action"] == "keep"
    assert items["utterance-0002.wav"]["reason"] == "no_transcript"
    assert plan["raw_text_range"] == {
        "start": {"session_id": _CONSOLIDATION_SESSION, "event_position": 0},
        "end": {"session_id": _CONSOLIDATION_SESSION, "event_position": 1},
    }


@pytest.mark.asyncio
async def test_consolidation_execute_api_removes_audio_and_status_reflects_it(
    tmp_path: Path,
) -> None:
    store, transcripts, planner, executor, _archive = _consolidation_setup(tmp_path)
    store.write_media(_CONSOLIDATION_SESSION, "utterance-0001.wav", b"aaa")
    ref = store.append(
        _journal_event(
            session_id=_CONSOLIDATION_SESSION,
            timestamp="2026-08-01T14:00:00+01:00",
            source="voice",
            role="user",
            text="",
            media=("utterance-0001.wav",),
        )
    )
    transcripts.upsert_transcript(ref, "первое", TranscriptSource.GENERATED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_consolidation_planner=planner,
        journal_consolidation_executor=executor,
    )
    info = await server.start()
    root = (
        f"http://127.0.0.1:{info.port}/api/journal/consolidation/"
        f"{_CONSOLIDATION_SESSION}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            before_status = await _get_json(session, f"{root}/status?token=valid-token")
            assert before_status["found"] is False

            executed = await session.post(f"{root}/execute?token=valid-token")
            assert executed.status == 200
            executed_payload = await executed.json()
            assert executed_payload["outcome"] == "executed"
            run = executed_payload["run"]
            assert run["status"] == "completed"
            assert run["removed_count"] == 1
            assert run["bytes_reclaimed"] == 3

            after_status = await _get_json(session, f"{root}/status?token=valid-token")
            assert after_status["found"] is True
            assert after_status["run"] == run
    finally:
        await server.stop()

    assert not (tmp_path / _CONSOLIDATION_SESSION / "utterance-0001.wav").exists()


@pytest.mark.asyncio
async def test_consolidation_api_active_session_guard_blocks_execute(
    tmp_path: Path,
) -> None:
    store, transcripts, planner, executor, _archive = _consolidation_setup(tmp_path)
    store.write_media(_CONSOLIDATION_SESSION, "utterance-0001.wav", b"aaa")
    ref = store.append(
        _journal_event(
            session_id=_CONSOLIDATION_SESSION,
            timestamp="2026-08-01T14:00:00+01:00",
            source="voice",
            role="user",
            text="",
            media=("utterance-0001.wav",),
        )
    )
    transcripts.upsert_transcript(ref, "первое", TranscriptSource.GENERATED)
    server = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        token_factory=lambda: "valid-token",
        journal_active_session_id=lambda: _CONSOLIDATION_SESSION,
        journal_consolidation_planner=planner,
        journal_consolidation_executor=executor,
    )
    info = await server.start()
    root = (
        f"http://127.0.0.1:{info.port}/api/journal/consolidation/"
        f"{_CONSOLIDATION_SESSION}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            plan_payload = await _get_json(session, f"{root}?token=valid-token")
            assert plan_payload["plan"]["plan_status"] == "active_session"

            executed = await session.post(f"{root}/execute?token=valid-token")
            assert executed.status == 200
            executed_payload = await executed.json()
            assert executed_payload["outcome"] == "active_session"
            assert executed_payload["run"] is None
    finally:
        await server.stop()

    assert (tmp_path / _CONSOLIDATION_SESSION / "utterance-0001.wav").exists()


@pytest.mark.asyncio
async def test_consolidation_api_hidden_and_token(tmp_path: Path) -> None:
    _store, _transcripts, planner, executor, _archive = _consolidation_setup(tmp_path)
    hidden = UiTransportServer(
        EventBus(),
        _FakeControlApi(),
        state=UiStateStore(visibility_mode=VisibilityMode.HIDDEN),
        token_factory=lambda: "valid-token",
        journal_consolidation_planner=planner,
        journal_consolidation_executor=executor,
    )
    info = await hidden.start()
    root = (
        f"http://127.0.0.1:{info.port}/api/journal/consolidation/"
        f"{_CONSOLIDATION_SESSION}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            hidden_plan = await _get_json(session, f"{root}?token=valid-token")
            assert hidden_plan == {"status": "hidden"}
            hidden_status = await _get_json(session, f"{root}/status?token=valid-token")
            assert hidden_status == {"status": "hidden"}
            hidden_execute = await session.post(f"{root}/execute?token=valid-token")
            assert (await hidden_execute.json()) == {"status": "hidden"}

            missing_token = await session.get(root)
            assert missing_token.status == 401
    finally:
        await hidden.stop()


@pytest.mark.asyncio
async def test_consolidation_api_unavailable_without_planner_or_executor() -> None:
    server = UiTransportServer(
        EventBus(), _FakeControlApi(), token_factory=lambda: "valid-token"
    )
    info = await server.start()
    root = (
        f"http://127.0.0.1:{info.port}/api/journal/consolidation/"
        f"{_CONSOLIDATION_SESSION}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            plan_response = await session.get(f"{root}?token=valid-token")
            assert plan_response.status == 503
            status_response = await session.get(f"{root}/status?token=valid-token")
            assert status_response.status == 503
            execute_response = await session.post(f"{root}/execute?token=valid-token")
            assert execute_response.status == 503
    finally:
        await server.stop()


def _journal_clock():
    from datetime import UTC, datetime

    return lambda: datetime(2026, 7, 16, 15, 30, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_lan_capture_widens_the_axis_when_the_call_finishes():
    """A camera tool is registered local, because its default source is a
    USB device; only the finished call knows a LAN source was used. The
    axis must follow that, and a later local call must not pull it back."""
    bus = EventBus()
    server = UiTransportServer(bus, _FakeControlApi())
    server._subscribe_to_bus()
    try:
        await bus.publish(
            ToolCallStarted,
            ToolCallStarted(
                correlation_id="call-1",
                tool_name="capture_camera_image",
                provider="builtin",
                arguments={"source": "wide"},
                outbound_summary="builtin.capture_camera_image(source='wide')",
                timestamp=1.0,
                data_boundary=DataBoundary.LOCAL,
            ),
        )
        assert server.state.snapshot()["data_source"] == {"source": "local_only"}

        await bus.publish(
            ToolCallFinished,
            ToolCallFinished(
                correlation_id="call-1",
                tool_name="capture_camera_image",
                provider="builtin",
                outbound_summary="builtin.capture_camera_image(source='wide')",
                duration_seconds=1.9,
                ok=True,
                error=None,
                data_boundary=DataBoundary.LAN,
            ),
        )
        assert server.state.snapshot()["data_source"] == {"source": "lan"}

        await bus.publish(
            ToolCallFinished,
            ToolCallFinished(
                correlation_id="call-2",
                tool_name="capture_camera_image",
                provider="builtin",
                outbound_summary="builtin.capture_camera_image(source='desk')",
                duration_seconds=3.5,
                ok=True,
                error=None,
                data_boundary=DataBoundary.LOCAL,
            ),
        )
        assert server.state.snapshot()["data_source"] == {"source": "lan"}
    finally:
        for event_type, handler in server._subscriptions:
            bus.unsubscribe(event_type, handler)
