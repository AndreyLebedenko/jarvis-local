import asyncio
import sys
import types
from dataclasses import fields
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import pytest
from _support_from_test_main import (
    _FakeBackend,
    _FakeCaptureInput,
    _FakeTransport,
    _FakeTtsOutput,
)

import jarvis.app as main_module
import jarvis.inputs.hotkeys as hotkeys_module
from jarvis.app import (
    _on_interrupt_requested,
    _seed_microphone_health,
    build_app,
    create_live_status_console,
    run,
    wire,
    wire_status_console,
)
from jarvis.audio.input import UtteranceChunk
from jarvis.audio.replay import ReplayPlayer
from jarvis.core.config import (
    HotkeySettings,
    JournalSettings,
    McpModeSettings,
    McpSettings,
    Settings,
    UiSettings,
)
from jarvis.core.lifecycle import WarmupCompleted, WarmupStarted
from jarvis.core.run_mode import RunMode
from jarvis.dialog.voice_guide import (
    VoiceGuideAccepted,
    VoiceGuideRejected,
    VoiceGuideRejection,
    VoiceGuideRequest,
    VoiceGuideService,
)
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.inputs.interrupt import InterruptRequested
from jarvis.journal.external_canvas import SPEECH_ORIGIN_METADATA_KEY, SpeechOrigin
from jarvis.mcp_mode.server import (
    McpPortUnavailableError,
    McpServerState,
    McpServerStatusChanged,
)
from jarvis.mcp_mode.token import McpTokenFileError
from jarvis.ui.contract import (
    EventLevel,
    HealthStatus,
    ModuleId,
    RuntimeState,
    SystemEvent,
)
from jarvis.ui.status_console import runtime_state_payload
from jarvis.ui.text import ui_text

# Every HotkeySettings field and whether --mcp-mode binds it. A new field
# fails test_every_hotkey_has_an_mcp_mode_verdict until it gets a verdict here.
MCP_MODE_BINDS_HOTKEY = {
    "screenshot_full": False,
    "screenshot_region": False,
    "shutdown": True,
    "mic_sleep_toggle": False,
    "clipboard_submit": False,
    "thinking_toggle": False,
    "interrupt": True,
    "response_mode_toggle": False,
}


def test_every_hotkey_has_an_mcp_mode_verdict():
    assert set(MCP_MODE_BINDS_HOTKEY) == {
        field.name for field in fields(HotkeySettings)
    }


class _RecordingMicrophone:
    is_awake = True
    capture_failed = False

    def __init__(self) -> None:
        self.loop_starts = 0

    async def run_microphone_loop(self) -> None:
        self.loop_starts += 1

    async def stop(self) -> None:
        return None


class _RecordingHotkeyProvider:
    def __init__(self, registered: dict) -> None:
        self._registered = registered

    def register(self, binding, callback) -> None:
        self._registered[binding] = callback

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _RecordingVoiceGuide:
    def __init__(self, order: list[str]) -> None:
        self._order = order

    def start(self) -> None:
        self._order.append("guide started")

    def interrupt(self) -> None:
        self._order.append("guide interrupted")

    async def close(self) -> None:
        self._order.append("guide closed")


class _RecordingServer:
    def __init__(self, order: list[str]) -> None:
        self._order = order

    def start(self) -> asyncio.Task[None]:
        return asyncio.create_task(self._serve())

    async def _serve(self) -> None:
        self._order.append("server started")
        try:
            await asyncio.Event().wait()
        finally:
            self._order.append("server stopped")


class _RecordingJournal:
    session_id = None

    def __init__(self, order: list[str]) -> None:
        self._order = order

    async def wait_for_pending(self) -> None:
        self._order.append("journal flushed")


class _RecordingMcpHost:
    enabled = False

    def __init__(self) -> None:
        self.enable_calls = 0

    async def enable(self) -> None:
        self.enable_calls += 1

    async def disable(self) -> None:
        pass


class _SilentCues:
    async def play(self, cue: str) -> None:
        pass

    async def wait_for_pending(self) -> None:
        pass


def _mcp_mode_settings(tmp_path) -> Settings:
    return Settings(
        journal=JournalSettings(enabled=False, root=str(tmp_path / "journal")),
        mcp=McpSettings(enabled=True),
    )


def _mcp_mode_app(settings: Settings, microphone=None):
    return build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=microphone or _RecordingMicrophone(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
        run_mode=RunMode.MCP,
    )


async def _until(condition, attempts: int = 200) -> None:
    for _ in range(attempts):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


def _isolate(app, order: list[str]) -> None:
    app.voice_guide = _RecordingVoiceGuide(order)
    app.journal_recorder = _RecordingJournal(order)
    app.mcp_host = _RecordingMcpHost()
    app.history_projection_lifecycle = None
    app.sound_cues = _SilentCues()


@pytest.fixture
def quiet_run(monkeypatch):
    monkeypatch.setattr(main_module, "configure_logging", lambda settings: None)
    monkeypatch.setattr(main_module, "ensure_generated", lambda settings: None)


@pytest.fixture
def fake_hotkeys(monkeypatch) -> dict:
    """Every hotkey listener gets a recording provider, so a run under test
    never registers a real global hotkey."""
    registered: dict = {}
    monkeypatch.setattr(
        hotkeys_module,
        "WindowsHotkeyProvider",
        lambda: _RecordingHotkeyProvider(registered),
    )
    return registered


async def test_mcp_mode_run_composes_the_voice_guide_and_nothing_that_takes_input(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _mcp_mode_settings(tmp_path)
    microphone = _RecordingMicrophone()
    app = _mcp_mode_app(settings, microphone)
    order: list[str] = []
    _isolate(app, order)
    registered = fake_hotkeys

    def prepare_server(mcp_mode: McpModeSettings, voice_guide, bus) -> _RecordingServer:
        assert mcp_mode is settings.mcp_mode
        assert voice_guide is app.voice_guide
        assert bus is app.bus
        order.append("server prepared")
        return _RecordingServer(order)

    running = asyncio.create_task(
        run(
            settings=settings,
            app=app,
            shutdown_provider=_RecordingHotkeyProvider(registered),
            run_mode=RunMode.MCP,
            prepare_mcp_server=prepare_server,
        )
    )
    await _until(lambda: settings.hotkeys.interrupt in registered)
    await _until(lambda: "server started" in order)
    registered[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    bound = {name for name, binds in MCP_MODE_BINDS_HOTKEY.items() if binds}
    assert set(registered) == {getattr(settings.hotkeys, name) for name in bound}
    assert microphone.loop_starts == 0
    assert app.mcp_host.enable_calls == 0
    assert order == [
        "server prepared",
        "guide started",
        "server started",
        "server stopped",
        "guide closed",
        "journal flushed",
    ]


async def test_mcp_mode_closes_the_guide_and_flushes_the_journal_when_startup_fails(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _mcp_mode_settings(tmp_path)
    app = _mcp_mode_app(settings)
    order: list[str] = []
    _isolate(app, order)

    class _FailingProvider(_RecordingHotkeyProvider):
        def start(self) -> None:
            raise RuntimeError("hotkey registration failed")

    with pytest.raises(RuntimeError, match="hotkey registration failed"):
        await run(
            settings=settings,
            app=app,
            shutdown_provider=_FailingProvider({}),
            run_mode=RunMode.MCP,
        )

    assert order == ["guide closed", "journal flushed"]


async def test_an_mcp_mode_run_without_a_voice_guide_fails_instead_of_serving_nothing(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _mcp_mode_settings(tmp_path)
    app = _mcp_mode_app(settings)
    order: list[str] = []
    _isolate(app, order)
    app.voice_guide = None

    def prepare_server(mcp_mode, voice_guide, bus):
        order.append("server prepared")

    with pytest.raises(RuntimeError, match="voice guide"):
        await asyncio.wait_for(
            run(
                settings=settings,
                app=app,
                shutdown_provider=_RecordingHotkeyProvider(fake_hotkeys),
                run_mode=RunMode.MCP,
                prepare_mcp_server=prepare_server,
            ),
            timeout=5,
        )

    assert "server prepared" not in order


_STARTUP_FAILURES = [
    pytest.param(
        McpTokenFileError(Path("mcp_mode.token"), "is empty"),
        ui_text("mcp_mode_token_file_unusable", "en", path="mcp_mode.token"),
        id="token-file",
    ),
    pytest.param(
        McpPortUnavailableError(47821, "address in use"),
        ui_text("mcp_mode_port_unavailable", "en", port=47821),
        id="port",
    ),
]


def _failing_preparer(error: Exception):
    def prepare(mcp_mode, voice_guide, bus):
        raise error

    return prepare


@pytest.mark.parametrize(("error", "ui_message"), _STARTUP_FAILURES)
async def test_a_headless_mcp_mode_startup_failure_ends_the_run_with_that_error(
    tmp_path, quiet_run, fake_hotkeys, error, ui_message
):
    del ui_message
    settings = _mcp_mode_settings(tmp_path)
    app = _mcp_mode_app(settings)
    order: list[str] = []
    _isolate(app, order)

    with pytest.raises(type(error)):
        await asyncio.wait_for(
            run(
                settings=settings,
                app=app,
                shutdown_provider=_RecordingHotkeyProvider(fake_hotkeys),
                run_mode=RunMode.MCP,
                prepare_mcp_server=_failing_preparer(error),
            ),
            timeout=5,
        )

    assert order == ["guide closed", "journal flushed"]


@pytest.mark.parametrize(("error", "ui_message"), _STARTUP_FAILURES)
async def test_a_console_mcp_mode_startup_failure_is_reported_and_jarvis_keeps_running(
    tmp_path, quiet_run, fake_hotkeys, monkeypatch, error, ui_message
):
    monkeypatch.setattr(main_module, "wire_status_console", lambda *args: [])
    settings = _mcp_mode_settings(tmp_path)
    app = _mcp_mode_app(settings)
    order: list[str] = []
    _isolate(app, order)
    statuses: list[McpServerStatusChanged] = []
    system_events: list[SystemEvent] = []

    async def record_status(event: McpServerStatusChanged) -> None:
        statuses.append(event)

    async def record_system_event(event: SystemEvent) -> None:
        system_events.append(event)

    app.bus.subscribe(McpServerStatusChanged, record_status)
    app.bus.subscribe(SystemEvent, record_system_event)
    console = types.SimpleNamespace(
        api=types.SimpleNamespace(set_shutdown_event=lambda event: None),
        transport=None,
        close=lambda: None,
    )
    registered = fake_hotkeys

    running = asyncio.create_task(
        run(
            settings=settings,
            app=app,
            live_console=console,
            shutdown_provider=_RecordingHotkeyProvider(registered),
            run_mode=RunMode.MCP,
            prepare_mcp_server=_failing_preparer(error),
        )
    )
    await _until(lambda: settings.hotkeys.interrupt in registered)
    still_running = not running.done()
    registered[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert still_running
    assert statuses == [
        McpServerStatusChanged(McpServerState.FAILED, reason=str(error))
    ]
    mcp_events = [event for event in system_events if event.source == "MCP_MODE"]
    assert [(event.level, event.message) for event in mcp_events] == [
        (EventLevel.ERROR, ui_message)
    ]
    assert order == ["guide closed", "journal flushed"]


async def test_run_refuses_an_app_built_for_another_run_mode(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _mcp_mode_settings(tmp_path)
    app = _mcp_mode_app(settings)
    _isolate(app, [])

    with pytest.raises(ValueError, match="run mode mcp, not normal"):
        await asyncio.wait_for(
            run(
                settings=settings,
                app=app,
                shutdown_provider=_RecordingHotkeyProvider(fake_hotkeys),
                run_mode=RunMode.NORMAL,
            ),
            timeout=2,
        )


async def test_the_interrupt_reaches_the_voice_guide_before_the_shared_player(
    tmp_path,
):
    app = _mcp_mode_app(_mcp_mode_settings(tmp_path))
    order: list[str] = []
    app.voice_guide = _RecordingVoiceGuide(order)

    class _RecordingPlayer:
        def cancel(self) -> bool:
            order.append("player cancelled")
            return False

    app.replay_player = _RecordingPlayer()

    await _on_interrupt_requested(app, InterruptRequested())

    assert order == ["guide interrupted", "player cancelled"]


async def test_nothing_published_in_mcp_mode_can_start_a_user_turn(
    tmp_path, monkeypatch
):
    turn_starts: list[str] = []
    monkeypatch.setattr(
        ReplayPlayer, "cancel", lambda self: turn_starts.append("turn") or False
    )
    app = _mcp_mode_app(_mcp_mode_settings(tmp_path))
    subscriptions = wire(app)

    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )
    await app.bus.publish(
        ClipboardSubmitted,
        ClipboardSubmitted(text="paste", truncated=False, is_empty=False),
    )
    await app.bus.publish(
        ScreenshotCaptured,
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1),
    )

    input_events = {UtteranceChunk, ClipboardSubmitted, ScreenshotCaptured}
    assert [event for event, _ in subscriptions if event in input_events] == []
    assert turn_starts == []
    assert app.orchestrator.is_busy is False
    assert app.backend.calls == []


def test_only_mcp_mode_builds_a_voice_guide(tmp_path):
    settings = _mcp_mode_settings(tmp_path)
    normal = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_RecordingMicrophone(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )

    assert normal.voice_guide is None
    assert isinstance(_mcp_mode_app(settings).voice_guide, VoiceGuideService)


async def test_the_voice_guide_takes_its_queue_capacity_from_mcp_mode_config(tmp_path):
    settings = Settings(
        journal=JournalSettings(enabled=False, root=str(tmp_path / "journal")),
        mcp_mode=McpModeSettings(queue_capacity=1),
    )
    guide = _mcp_mode_app(settings).voice_guide
    request = VoiceGuideRequest(canvas="An answer.")

    results = [guide.enqueue(request), guide.enqueue(request)]
    await guide.close()

    assert results == [
        VoiceGuideAccepted(position=1, speech_origin=SpeechOrigin.DERIVATIVE),
        VoiceGuideRejected(VoiceGuideRejection.QUEUE_FULL),
    ]


@pytest.mark.parametrize("canvas_speech", ["derivative", "verbatim"])
async def test_the_voice_guide_speaks_a_canvas_as_mcp_mode_config_says(
    tmp_path, canvas_speech
):
    settings = Settings(
        journal=JournalSettings(enabled=True, root=str(tmp_path / "journal")),
        mcp_mode=McpModeSettings(canvas_speech=canvas_speech),
    )
    app = _mcp_mode_app(settings)

    app.voice_guide.enqueue(VoiceGuideRequest(canvas="An answer."))
    await app.voice_guide.close()
    await app.journal_recorder.wait_for_pending()

    events = app.journal_store.read_session(app.journal_recorder.session_id).events
    assert [event.metadata[SPEECH_ORIGIN_METADATA_KEY] for event in events] == [
        canvas_speech
    ]


class _FakeWindow:
    def __init__(self) -> None:
        self.loaded_urls: list[str] = []

    def create(self, on_closed=None, url=None) -> None:
        return None

    def load_url(self, url: str) -> None:
        self.loaded_urls.append(url)

    def close(self) -> None:
        pass


def test_the_status_console_path_composes_mcp_mode_end_to_end(tmp_path, monkeypatch):
    settings = _mcp_mode_settings(tmp_path)
    app = _mcp_mode_app(settings)
    app.mcp_host = _RecordingMcpHost()
    app.history_projection_lifecycle = None
    app.ui_config_path = tmp_path / "config.ui.toml"
    window = _FakeWindow()
    seen: dict = {}

    def fake_build_app(settings, run_mode):
        seen["built_for"] = run_mode
        return app

    async def fake_run(
        settings=None,
        app=None,
        live_console=None,
        debug=False,
        run_mode=RunMode.NORMAL,
    ) -> None:
        seen["run_mode"] = run_mode
        transport = live_console.transport
        port = urlsplit(window.loaded_urls[0]).port
        live_console.api.set_loop(asyncio.get_running_loop())
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"http://127.0.0.1:{port}/api/journal/input"
                    f"?token={transport.token}",
                    json={},
                )
                seen["input"] = (response.status, await response.json())
            seen["snapshot"] = transport.state.snapshot()["run_mode"]["mode"]
            live_console.api.save_config_selection("model", "microphone")
            await asyncio.sleep(0.05)
        finally:
            await transport.stop()

    monkeypatch.setattr(main_module, "build_app", fake_build_app)
    monkeypatch.setattr(main_module, "StatusConsoleWindow", lambda: window)
    monkeypatch.setattr(main_module, "run", fake_run)
    monkeypatch.setitem(
        sys.modules, "webview", types.SimpleNamespace(start=lambda start: start())
    )

    main_module.run_with_status_console(
        settings=settings, include_touchstrip=False, run_mode=RunMode.MCP
    )

    assert seen["built_for"] is RunMode.MCP
    assert seen["run_mode"] is RunMode.MCP
    assert seen["snapshot"] == "mcp"
    assert seen["input"] == (
        403,
        {"status": "rejected", "reason": "mcp_mode", "action": "journal_input"},
    )
    written = app.ui_config_path.read_text(encoding="utf-8")
    assert "[mcp]\nenabled = true" in written


def test_the_microphone_chip_does_not_claim_a_listening_microphone_in_mcp_mode(
    tmp_path,
):
    health = _seed_microphone_health(_mcp_mode_app(_mcp_mode_settings(tmp_path)))

    assert health.module is ModuleId.MICROPHONE
    assert health.status is HealthStatus.UNAVAILABLE
    assert health.detail == "off in MCP mode"


@pytest.mark.parametrize(
    ("run_mode", "language", "expected"),
    [
        (RunMode.NORMAL, "en", (RuntimeState.LISTENING, "Waiting for a request")),
        (RunMode.MCP, "en", (RuntimeState.MCP_WAITING, "Waiting for a request")),
        (RunMode.MCP, "ru", (RuntimeState.MCP_WAITING, "Ожидаю запрос")),
    ],
)
async def test_after_warm_up_the_orb_rests_in_the_run_modes_ready_state(
    tmp_path, run_mode, language, expected
):
    settings = Settings(
        journal=JournalSettings(enabled=False, root=str(tmp_path / "journal")),
        ui=UiSettings(language=language),
    )
    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_RecordingMicrophone(),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
        run_mode=run_mode,
    )
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(WarmupStarted, WarmupStarted())
    await app.bus.publish(WarmupCompleted, WarmupCompleted(succeeded=True))

    runtime_calls = [args for kind, args in transport.calls if kind == "runtime"]
    assert runtime_calls[-1] == expected


@pytest.mark.parametrize(
    ("language", "label"), [("en", "MCP waiting"), ("ru", "MCP ожидает")]
)
def test_the_mcp_waiting_orb_label_is_localized(language, label):
    payload = runtime_state_payload(RuntimeState.MCP_WAITING, language=language)

    assert payload["state"] == "mcp_waiting"
    assert payload["label"] == label
