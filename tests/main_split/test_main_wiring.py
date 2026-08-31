import asyncio

import pytest
from _support_from_test_main import (
    _fake_app,
    _FakeAudioInputForEcho,
    _FakeBackend,
    _FakeCaptureInput,
    _FakeStatusSurface,
    _FakeTransport,
    _FakeTtsOutput,
)

from jarvis.app import (
    App,
    _microphone_health,
    build_app,
    create_live_status_console,
    parse_args,
    unwire,
    wire,
    wire_status_console,
)
from jarvis.audio.debug_metrics import on_utterance_captured
from jarvis.audio.input import (
    MicSleepToggled,
    UtteranceChunk,
)
from jarvis.audio.tts_mute import TtsSpeechEnabledChanged
from jarvis.core.config import (
    JournalSettings,
    Settings,
    TtsSettings,
    VadSettings,
)
from jarvis.dialog.backend import (
    LatencyMetrics,
    ResponseComplete,
    ResponseToken,
)
from jarvis.dialog.response_mode import (
    ResponseMode,
    ResponseModeChanged,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
)
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.inputs.interrupt import InterruptRequested
from jarvis.tools.host import (
    McpModuleStatus,
    McpModuleStatusChanged,
)
from jarvis.ui.contract import (
    DataLocality,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    VisibilityMode,
)

# --- wiring --------------------------------------------------------------


def test_wire_registers_expected_subscriptions():
    app = _fake_app()

    subscriptions = wire(app)
    event_types = [event_type for event_type, _handler in subscriptions]

    # Two: the orchestrator's own turn handling, plus the debug-transcript
    # metrics bridge (on_utterance_captured), which is unconditional and
    # a no-op unless debug is on.
    assert event_types.count(UtteranceChunk) == 2
    assert event_types.count(ScreenshotCaptured) == 1
    assert event_types.count(ClipboardSubmitted) == 1
    assert event_types.count(ResponseToken) == 2  # tts_output + orchestrator
    # A single coordinating handler, not three concurrent subscribers -
    # see _on_full_response_complete's docstring for why that mattered.
    assert event_types.count(ResponseComplete) == 1
    assert event_types.count(MicSleepToggled) == 1
    assert event_types.count(ReasoningLevelChanged) == 1
    assert event_types.count(ResponseModeChanged) == 1
    assert event_types.count(InterruptRequested) == 1
    assert event_types.count(TtsSpeechEnabledChanged) == 1

    handlers = [handler for _event_type, handler in subscriptions]
    assert app.orchestrator.on_utterance in handlers
    assert on_utterance_captured in handlers
    assert app.orchestrator.on_screenshot in handlers
    assert app.orchestrator.on_clipboard in handlers


async def test_muting_tts_cancels_in_flight_speech_but_unmuting_does_not():
    app = _fake_app()
    wire(app)

    await app.bus.publish(
        TtsSpeechEnabledChanged, TtsSpeechEnabledChanged(enabled=False)
    )
    await app.bus.publish(
        TtsSpeechEnabledChanged, TtsSpeechEnabledChanged(enabled=True)
    )

    assert app.tts_output.cancel_calls == 1


def test_build_app_seeds_tts_mute_state_from_settings():
    settings = Settings(
        journal=JournalSettings(enabled=False), tts=TtsSettings(enabled=False)
    )

    app = build_app(settings, backend=_FakeBackend(), tts_output=_FakeTtsOutput())

    assert app.tts_mute_state is not None
    assert app.tts_mute_state.enabled is False


def test_build_app_wires_one_shared_solo_session_state():
    settings = Settings(journal=JournalSettings(enabled=False))

    app = build_app(settings, backend=_FakeBackend(), tts_output=_FakeTtsOutput())

    assert app.solo_session_state is not None
    assert app.solo_session_state.enabled is False
    # Same object reaches the Orchestrator - toggling app.solo_session_state
    # actually changes what the running orchestrator sees, not a copy.
    assert app.orchestrator._solo_session_state is app.solo_session_state


def test_create_live_status_console_shares_one_api_between_surfaces():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()

    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )

    assert live_console.transport is None
    assert live_console.console is console
    assert live_console.touchstrip is touchstrip


def test_live_status_console_closes_all_surfaces():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()
    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )

    live_console.close()
    live_console.close()

    assert console.close_calls == 2
    assert touchstrip.close_calls == 2


def _builtin_tool_payloads(app: App) -> list[dict[str, object]]:
    """Descriptions are read from the app's own registry rather than
    pinned here: the tooltip shows whatever the model-facing text happens
    to be, and pinning the prose would turn an assertion about plumbing
    into an assertion about wording (task-tool-rows-name-capabilities)."""

    def description(name: str) -> str:
        assert app.mcp_host is not None
        tool = app.mcp_host.registry.get(name)
        assert tool is not None
        return tool.description

    return [
        {
            "name": "capture_camera_image",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": False,
            "available": True,
            "description": description("capture_camera_image"),
        },
        {
            "name": "list_session_files",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("list_session_files"),
        },
        {
            "name": "read_history",
            "provider": "history",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("read_history"),
        },
        {
            "name": "read_history_ranges",
            "provider": "history",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("read_history_ranges"),
        },
        {
            "name": "read_session_text",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("read_session_text"),
        },
        {
            "name": "remember",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("remember"),
        },
        {
            "name": "search_history",
            "provider": "history",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("search_history"),
        },
        {
            "name": "set_reasoning_level",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("set_reasoning_level"),
        },
        {
            "name": "stat_session_file",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("stat_session_file"),
        },
        {
            "name": "view_session_image",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("view_session_image"),
        },
        {
            "name": "write_session_file",
            "provider": "builtin",
            "provider_kind": "builtin",
            "enabled": True,
            "available": True,
            "description": description("write_session_file"),
        },
    ]


async def test_wire_status_console_seeds_the_transport_snapshot():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport

    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    # Runtime state is no longer seeded here: the initial snapshot value is
    # set where the UiStateStore is constructed, and every transition comes
    # from RuntimeStateTracker (subscribed by this call, hence non-empty
    # subscriptions).
    assert len(subscriptions) > 0
    assert transport.calls == [
        ("model", app.settings.backend.model),
        ("locality", DataLocality.LOCAL),
        (
            "mcp",
            {
                "status": "off",
                "enabled": False,
                "tools": [],
                "local_tools": _builtin_tool_payloads(app),
            },
        ),
        ("thinking", ReasoningLevel.OFF),
        ("response_mode", ResponseMode.TEXT),
        ("visibility", VisibilityMode.OPEN),
        (
            "module",
            ModuleHealth(
                module=ModuleId.MICROPHONE, status=HealthStatus.OK, detail="listening"
            ),
        ),
        (
            "module",
            ModuleHealth(
                module=ModuleId.CAMERA,
                status=HealthStatus.UNAVAILABLE,
                detail="privacy off",
            ),
        ),
        (
            "module",
            ModuleHealth(
                module=ModuleId.TTS, status=HealthStatus.OK, detail="speaking"
            ),
        ),
    ]

    unwire(app, subscriptions)


@pytest.mark.asyncio
async def test_wire_status_console_projects_authoritative_mcp_status_changes():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(
        McpModuleStatusChanged,
        McpModuleStatusChanged(status=McpModuleStatus.CONNECTING),
    )

    assert transport.calls[-1] == (
        "mcp",
        {
            "status": "connecting",
            "enabled": False,
            "tools": [],
            "local_tools": _builtin_tool_payloads(app),
        },
    )
    unwire(app, subscriptions)


def test_microphone_health_reports_user_muted_as_not_in_use():
    assert _microphone_health(False, "en") == ModuleHealth(
        module=ModuleId.MICROPHONE,
        status=HealthStatus.UNAVAILABLE,
        detail="not in use",
    )


def test_microphone_health_keeps_the_v1_2_10_russian_muted_wording():
    assert _microphone_health(False, "ru").detail == "не используется"


async def test_wire_status_console_leaves_bus_projection_to_the_transport_server():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(MicSleepToggled, MicSleepToggled(is_awake=False))
    await app.bus.publish(MicSleepToggled, MicSleepToggled(is_awake=True))

    # Only the nine snapshot seeds: mic-toggle projection belongs to the
    # real transport server's own bus subscription, not to this wiring.
    assert len(transport.calls) == 9
    assert transport.calls[-1][0] == "module"

    unwire(app, subscriptions)


async def test_accepted_voice_turn_renders_thinking_through_the_tracker():
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    wire_status_console(app, live_console, asyncio.get_running_loop())
    wire(app)

    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )

    runtime_calls = [call for call in transport.calls if call[0] == "runtime"]
    assert ("runtime", (RuntimeState.THINKING, "Processing voice...")) in runtime_calls


async def test_rejected_busy_turn_does_not_render_thinking():
    """The busy guard lives in the Orchestrator alone: a turn rejected
    there publishes no TurnAccepted, so the tracker never announces
    THINKING - previously this required duplicating the busy check in the
    wire() closures."""
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    wire_status_console(app, live_console, asyncio.get_running_loop())
    wire(app)
    app.orchestrator._busy = True

    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )

    assert [call for call in transport.calls if call[0] == "runtime"] == []


async def test_unwire_removes_all_subscriptions():
    app = _fake_app()
    subscriptions = wire(app)

    unwire(app, subscriptions)

    # the orchestrator's own handler should no longer be subscribed - if
    # it were, backend.chat() would have been called
    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )
    assert app.backend.calls == []


async def test_wire_pushes_listening_state_after_response_complete():
    """Regression for a real live-session bug (2026-07-07): RuntimeState
    stayed stuck on SPEAKING ("Отвечаю") forever after the very first
    turn - nothing ever pushed the orb back to LISTENING once
    ResponseComplete fired, even though the engine kept handling later
    turns correctly in the background. Since v1.2.14 the guarantee is
    owned by one chain: _on_full_response_complete publishes
    TurnCompleted after the turn fully finishes, RuntimeStateTracker
    turns it into RuntimeStateChanged(LISTENING), and
    wire_status_console()'s render handler pushes it to the transport."""
    settings = Settings(
        vad=VadSettings(request_end_pause_seconds=0.001, resume_cooldown_seconds=0.001)
    )
    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_FakeAudioInputForEcho(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    wire_status_console(app, live_console, asyncio.get_running_loop())
    wire(app)

    # A real ResponseComplete only ever fires for a turn that set busy
    # (task-v1.7.0-2's claim_turn_end() requires it - see review finding
    # 1); publishing it without one is not a scenario this handler needs
    # to support. Setting busy directly, not via on_utterance(): this
    # test's _FakeBackend has no iter_chat() (build_app() wraps it in
    # ToolAwareDialog, which needs it), so a real turn would just fail.
    app.orchestrator._busy = True
    await app.bus.publish(
        ResponseComplete, ResponseComplete(metrics=LatencyMetrics(0.0, 0.0, 0.0, 1))
    )

    assert transport.calls[-1] == (
        "runtime",
        (RuntimeState.LISTENING, "Waiting for a request"),
    )


def test_parse_args_enables_status_console_without_touchstrip():
    args = parse_args(["--status-console", "--no-touchstrip"])

    assert args.status_console is True
    assert args.no_touchstrip is True
