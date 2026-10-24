import asyncio
import logging
import sys
import types
from dataclasses import fields
from urllib.parse import urlsplit

import aiohttp
import pytest
from _support_from_test_main import (
    _FakeBackend,
    _FakeCaptureInput,
    _FakeTtsOutput,
)

import jarvis.app as main_module
import jarvis.inputs.hotkeys as hotkeys_module
from jarvis.app import (
    _on_interrupt_requested,
    build_app,
    create_live_status_console,
    run,
    wire,
    wire_status_console,
)
from jarvis.app_proxy import (
    model_label_for,
    new_context_handler_for,
    text_submitter_for,
)
from jarvis.audio.input import UtteranceChunk
from jarvis.audio.replay import ReplayPlayer
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    HotkeySettings,
    JournalSettings,
    McpSettings,
    PersonalProxySettings,
    Settings,
)
from jarvis.core.debug_transcript import recording
from jarvis.core.lifecycle import (
    NewContextReason,
    NewContextResult,
    TextSubmissionReason,
    TextSubmissionResult,
)
from jarvis.core.run_mode import RunMode
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.inputs.interrupt import InterruptRequested
from jarvis.personal_proxy.request.proxy_inbox import TypedText, Utterance
from jarvis.personal_proxy.service.proxy_runtime import PersonalProxyRuntime
from jarvis.personal_proxy.service.proxy_submissions import ProxySubmissions
from jarvis.personal_proxy.startup.startup_failure import (
    ProxyStartupError,
    StartupFailureKind,
)
from jarvis.ui.contract import EventLevel, HealthStatus, ModuleId, SystemEvent
from jarvis.ui.text import ui_text

# Every HotkeySettings field and whether --personal-proxy binds it. A new field
# fails test_every_hotkey_has_a_personal_proxy_verdict until it gets a verdict.
PERSONAL_PROXY_BINDS_HOTKEY = {
    "screenshot_full": False,
    "screenshot_region": False,
    "shutdown": True,
    "mic_sleep_toggle": True,
    "clipboard_submit": False,
    "thinking_toggle": False,
    "interrupt": True,
    "response_mode_toggle": False,
}


def test_every_hotkey_has_a_personal_proxy_verdict():
    assert set(PERSONAL_PROXY_BINDS_HOTKEY) == {
        field.name for field in fields(HotkeySettings)
    }


class _RecordingMicrophone:
    is_awake = True
    capture_failed = False

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.loop_starts = 0

    async def run_microphone_loop(self) -> None:
        self.loop_starts += 1
        self._order.append("microphone loop started")

    async def stop(self) -> None:
        self._order.append("microphone stopped")


class _RecordingHotkeyProvider:
    def __init__(self, registered: dict) -> None:
        self._registered = registered

    def register(self, binding, callback) -> None:
        self._registered[binding] = callback

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _Service:
    def __init__(self) -> None:
        self.items: list = []

    def submit(self, item) -> None:
        self.items.append(item)


class _FakeRuntime:
    """Stands in for the prepared runtime and records the order of its life."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.stops = 0
        self.interrupts = 0
        self.texts: list[str] = []
        self.new_sessions = 0

    def start(self) -> None:
        self._order.append("proxy started")

    def interrupt(self) -> None:
        self.interrupts += 1
        self._order.append("proxy interrupted")

    async def stop(self) -> None:
        self.stops += 1
        self._order.append("proxy stopped")

    async def submit_text(self, text: str):
        self.texts.append(text)
        return TextSubmissionResult(TextSubmissionReason.ACCEPTED, 100)

    async def start_new_session(self):
        self.new_sessions += 1
        return NewContextResult(NewContextReason.ACCEPTED)


class _CountingJournal:
    session_id = None

    def __init__(self) -> None:
        self.flushes = 0

    async def wait_for_pending(self) -> None:
        self.flushes += 1


class _RecordingJournal:
    session_id = None

    async def wait_for_pending(self) -> None:
        pass


class _RecordingMcpHost:
    enabled = False

    def __init__(self) -> None:
        self.enable_calls = 0

    async def enable(self) -> None:
        self.enable_calls += 1

    async def disable(self) -> None:
        pass


class _SilentCues:
    def __init__(self) -> None:
        self.played: list[str] = []

    async def play(self, cue: str) -> None:
        self.played.append(cue)

    async def wait_for_pending(self) -> None:
        pass


class _FakeProxyTransport:
    def __init__(self) -> None:
        self.blocks: list = []
        self.health: list = []

    def set_module_health(self, health) -> None:
        self.health.append(health)

    def publish_proxy_block(self, payload) -> None:
        self.blocks.append(payload)

    def set_data_locality(self, locality) -> None:
        pass

    async def stop(self) -> None:
        pass


class _SeedRecorder:
    """Accepts every seeding call of wire_status_console and keeps the label."""

    def __init__(self) -> None:
        self.labels: list[str] = []

    def set_model_label(self, label: str) -> None:
        self.labels.append(label)

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


def _settings(tmp_path) -> Settings:
    return Settings(
        journal=JournalSettings(enabled=False, root=str(tmp_path / "journal")),
        mcp=McpSettings(enabled=True),
        personal_proxy=PersonalProxySettings(
            endpoint="https://api.example.test/v1", model="remote"
        ),
    )


def _proxy_app(settings: Settings, order: list[str] | None = None):
    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_RecordingMicrophone(order if order is not None else []),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
        run_mode=RunMode.PERSONAL_PROXY,
    )
    app.journal_recorder = _RecordingJournal()
    app.mcp_host = _RecordingMcpHost()
    app.history_projection_lifecycle = None
    app.sound_cues = _SilentCues()
    return app


async def _until(condition, attempts: int = 400) -> None:
    for _ in range(attempts):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


@pytest.fixture
def quiet_run(monkeypatch):
    monkeypatch.setattr(main_module, "configure_logging", lambda settings: None)
    monkeypatch.setattr(main_module, "ensure_generated", lambda settings: None)
    monkeypatch.setattr(main_module, "wire_status_console", lambda *args: [])


@pytest.fixture
def fake_hotkeys(monkeypatch) -> dict:
    registered: dict = {}
    monkeypatch.setattr(
        hotkeys_module,
        "WindowsHotkeyProvider",
        lambda: _RecordingHotkeyProvider(registered),
    )
    return registered


def _console(transport=None):
    return types.SimpleNamespace(
        api=types.SimpleNamespace(set_shutdown_event=lambda event: None),
        transport=transport or _FakeProxyTransport(),
        close=lambda: None,
    )


def _preparer(order: list[str], runtime: _FakeRuntime | None = None, error=None):
    runtime = runtime or _FakeRuntime(order)

    async def prepare(host):
        order.append("proxy prepared")
        if error is not None:
            raise error
        return runtime

    return prepare, runtime


def _start_run(settings, app, registered, console, prepare):
    return asyncio.create_task(
        run(
            settings=settings,
            app=app,
            live_console=console,
            shutdown_provider=_RecordingHotkeyProvider(registered),
            run_mode=RunMode.PERSONAL_PROXY,
            prepare_personal_proxy=prepare,
        )
    )


async def test_a_personal_proxy_run_binds_only_its_hotkeys_and_starts_the_microphone(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, runtime = _preparer(order)

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: "microphone loop started" in order)
    await _until(lambda: settings.hotkeys.interrupt in fake_hotkeys)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    bound = {name for name, binds in PERSONAL_PROXY_BINDS_HOTKEY.items() if binds}
    assert set(fake_hotkeys) == {getattr(settings.hotkeys, name) for name in bound}
    assert app.audio_input.loop_starts == 1
    assert app.mcp_host.enable_calls == 0
    assert app.backend.calls == []


async def test_the_proxy_is_prepared_then_started_and_stopped_before_the_microphone(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, runtime = _preparer(order)

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: "microphone loop started" in order)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert order[:2] == ["proxy prepared", "proxy started"]
    assert order.index("proxy stopped") < order.index("microphone stopped")
    assert runtime.stops == 1


async def test_a_failure_during_startup_still_stops_the_proxy(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, runtime = _preparer(order)

    class _FailingProvider(_RecordingHotkeyProvider):
        def start(self) -> None:
            raise RuntimeError("hotkey registration failed")

    with pytest.raises(RuntimeError, match="hotkey registration failed"):
        await run(
            settings=settings,
            app=app,
            live_console=_console(),
            shutdown_provider=_FailingProvider({}),
            run_mode=RunMode.PERSONAL_PROXY,
            prepare_personal_proxy=prepare,
        )

    assert order == ["proxy prepared", "proxy stopped"]
    assert runtime.stops == 1


async def test_a_failing_proxy_stop_does_not_skip_the_rest_of_the_shutdown(
    tmp_path, quiet_run, fake_hotkeys, caplog
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    secret = "personal sentence"

    class _FailingStop(_FakeRuntime):
        async def stop(self) -> None:
            order.append("proxy stop failed")
            raise RuntimeError(secret)

    prepare, _ = _preparer(order, runtime=_FailingStop(order))
    app.journal_recorder = _CountingJournal()

    with caplog.at_level(logging.DEBUG):
        running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
        await _until(lambda: "microphone loop started" in order)
        fake_hotkeys[settings.hotkeys.shutdown]()
        await asyncio.wait_for(running, timeout=5)

    assert order.index("proxy stop failed") < order.index("microphone stopped")
    assert app.journal_recorder.flushes == 1
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_a_failing_proxy_stop_in_the_failure_path_keeps_the_original_error(
    tmp_path, quiet_run
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)

    class _FailingStop(_FakeRuntime):
        async def stop(self) -> None:
            raise RuntimeError("close failed")

    prepare, _ = _preparer(order, runtime=_FailingStop(order))

    class _FailingProvider(_RecordingHotkeyProvider):
        def start(self) -> None:
            raise OSError("hotkey registration failed")

    with pytest.raises(OSError, match="hotkey registration failed"):
        await run(
            settings=settings,
            app=app,
            live_console=_console(),
            shutdown_provider=_FailingProvider({}),
            run_mode=RunMode.PERSONAL_PROXY,
            prepare_personal_proxy=prepare,
        )


@pytest.mark.parametrize("kind", list(StartupFailureKind))
async def test_a_failed_validation_keeps_the_window_open_and_starts_nothing(
    tmp_path, quiet_run, fake_hotkeys, kind
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order, error=ProxyStartupError(kind))
    events: list[SystemEvent] = []

    async def record(event: SystemEvent) -> None:
        events.append(event)

    app.bus.subscribe(SystemEvent, record)

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: settings.hotkeys.shutdown in fake_hotkeys)
    await asyncio.sleep(0.05)
    still_running = not running.done()
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert still_running
    assert set(fake_hotkeys) == {settings.hotkeys.shutdown}
    assert order == ["proxy prepared", "microphone stopped"]
    assert app.audio_input.loop_starts == 0
    assert app.personal_proxy is None
    errors = [event for event in events if event.level is EventLevel.ERROR]
    assert [(event.source, event.message) for event in errors] == [
        ("PERSONAL_PROXY", ui_text(kind.ui_text_key, "en"))
    ]


async def test_a_failed_start_turns_the_microphone_chip_off(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order, error=ProxyStartupError(StartupFailureKind.OLLAMA))
    transport = _FakeProxyTransport()

    running = _start_run(settings, app, fake_hotkeys, _console(transport), prepare)
    await _until(lambda: settings.hotkeys.shutdown in fake_hotkeys)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert [(h.module, h.status, h.detail) for h in transport.health] == [
        (
            ModuleId.MICROPHONE,
            HealthStatus.UNAVAILABLE,
            "off: the personal proxy did not start",
        )
    ]


async def test_a_started_proxy_leaves_the_microphone_chip_alone(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order)
    transport = _FakeProxyTransport()

    running = _start_run(settings, app, fake_hotkeys, _console(transport), prepare)
    await _until(lambda: "microphone loop started" in order)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert transport.health == []


async def test_nothing_subscribes_to_the_bus_when_the_start_failed(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order, error=ProxyStartupError(StartupFailureKind.OLLAMA))

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: settings.hotkeys.shutdown in fake_hotkeys)
    handlers = app.bus._subscribers.get(UtteranceChunk, [])
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert list(handlers) == []


async def test_the_personal_proxy_needs_the_status_console(tmp_path, quiet_run):
    settings = _settings(tmp_path)
    app = _proxy_app(settings)

    with pytest.raises(ValueError, match="Status Console"):
        await run(settings=settings, app=app, run_mode=RunMode.PERSONAL_PROXY)


async def test_the_main_models_warm_up_does_not_run_in_the_personal_proxy(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order)

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: "microphone loop started" in order)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert app.backend.calls == []


# --- subscriptions and routing ---------------------------------------------------


async def test_only_the_proxy_gets_utterances_and_no_turn_path_is_subscribed(
    tmp_path, monkeypatch
):
    turn_starts: list[str] = []
    monkeypatch.setattr(
        ReplayPlayer, "cancel", lambda self: turn_starts.append("turn") or False
    )
    app = _proxy_app(_settings(tmp_path))
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


async def test_the_debug_utterance_recorder_is_not_subscribed_in_the_personal_proxy(
    tmp_path,
):
    app = _proxy_app(_settings(tmp_path))

    handlers = [handler for _, handler in wire(app)]

    assert main_module.on_utterance_captured not in handlers


async def test_a_started_runtime_sends_utterances_and_dock_text_to_the_inbox(
    tmp_path,
):
    app = _proxy_app(_settings(tmp_path))
    service = _Service()
    submissions = ProxySubmissions(
        service, text_max_chars=100, report_dropped=_never_dropped
    )
    app.personal_proxy = PersonalProxyRuntime(
        service=types.SimpleNamespace(
            start=lambda: None, interrupt=lambda: None, close=_noop
        ),
        submissions=submissions,
        bus=app.bus,
        client=types.SimpleNamespace(aclose=_noop),
    )
    app.personal_proxy.start()

    await app.bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"wav", start_seconds=0, end_seconds=1)
    )
    result = await text_submitter_for(app, RunMode.PERSONAL_PROXY)("Привет")
    await app.personal_proxy.stop()

    assert result.reason is TextSubmissionReason.ACCEPTED
    assert service.items == [Utterance(b"wav"), TypedText("Привет")]
    assert app.backend.calls == []


async def _never_dropped() -> None:
    raise AssertionError("nothing is dropped here")


async def _noop() -> None:
    return None


async def test_dock_text_while_the_proxy_is_starting_says_so_and_goes_nowhere(
    tmp_path,
):
    app = _proxy_app(_settings(tmp_path))

    result = await text_submitter_for(app, RunMode.PERSONAL_PROXY)("Привет")

    assert result.reason is TextSubmissionReason.UNAVAILABLE
    assert result.detail == ui_text("personal_proxy_starting", "en")
    assert app.backend.calls == []


@pytest.mark.parametrize("kind", list(StartupFailureKind))
async def test_dock_text_after_a_failed_start_gives_the_failure_reason_not_busy(
    tmp_path, kind
):
    app = _proxy_app(_settings(tmp_path))
    app.personal_proxy_failure = kind

    result = await text_submitter_for(app, RunMode.PERSONAL_PROXY)("Привет")

    assert result.reason is TextSubmissionReason.UNAVAILABLE
    assert result.detail == ui_text(kind.ui_text_key, "en")
    assert app.backend.calls == []


async def test_a_failed_start_remembers_its_kind_for_the_dock(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order, error=ProxyStartupError(StartupFailureKind.OLLAMA))

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: settings.hotkeys.shutdown in fake_hotkeys)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert app.personal_proxy_failure is StartupFailureKind.OLLAMA


async def test_the_listening_cue_is_not_played_when_the_start_failed(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order, error=ProxyStartupError(StartupFailureKind.OLLAMA))

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: settings.hotkeys.shutdown in fake_hotkeys)
    await asyncio.sleep(0.05)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert app.sound_cues.played == []


async def test_the_listening_cue_is_played_when_the_proxy_started(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    order: list[str] = []
    app = _proxy_app(settings, order)
    prepare, _ = _preparer(order)

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: "microphone loop started" in order)
    await _until(lambda: app.sound_cues.played)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert app.sound_cues.played == ["listening"]


def test_the_model_label_is_the_main_model_only_in_a_normal_run():
    settings = Settings(
        personal_proxy=PersonalProxySettings(
            endpoint="https://api.example.test/v1", model="check-model"
        )
    )

    assert model_label_for(settings, RunMode.NORMAL) == settings.backend.model
    assert model_label_for(settings, RunMode.PERSONAL_PROXY) == "check-model"


async def test_the_status_console_is_seeded_with_the_check_model_in_the_proxy(
    tmp_path,
):
    settings = _settings(tmp_path)
    app = build_app(
        settings,
        backend=_FakeBackend(),
        audio_input=_RecordingMicrophone([]),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
        run_mode=RunMode.PERSONAL_PROXY,
    )
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _SeedRecorder()
    live_console.transport = transport

    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    assert transport.labels == ["remote"]
    main_module.unwire(app, subscriptions)


async def test_the_normal_dock_text_still_reaches_the_orchestrator(tmp_path):
    app = build_app(
        _settings(tmp_path),
        backend=_FakeBackend(),
        audio_input=_RecordingMicrophone([]),
        tts_output=_FakeTtsOutput(),
        capture_input=_FakeCaptureInput(),
    )

    assert text_submitter_for(app, RunMode.NORMAL) == app.orchestrator.submit_text_input


async def test_the_interrupt_hotkey_reaches_the_proxy_before_the_shared_player(
    tmp_path,
):
    app = _proxy_app(_settings(tmp_path))
    order: list[str] = []
    app.personal_proxy = _FakeRuntime(order)

    class _RecordingPlayer:
        def cancel(self) -> bool:
            order.append("player cancelled")
            return False

    app.replay_player = _RecordingPlayer()

    await _on_interrupt_requested(app, InterruptRequested())

    assert order == ["proxy interrupted", "player cancelled"]


async def test_an_interrupt_without_a_proxy_is_harmless(tmp_path):
    app = _proxy_app(_settings(tmp_path))

    await _on_interrupt_requested(app, InterruptRequested())


# --- the status console path ---------------------------------------------------------


class _FakeWindow:
    def __init__(self) -> None:
        self.loaded_urls: list[str] = []

    def create(self, on_closed=None, url=None) -> None:
        return None

    def load_url(self, url: str) -> None:
        self.loaded_urls.append(url)

    def close(self) -> None:
        pass


def test_the_status_console_path_refuses_main_model_controls_and_routes_dock_text(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path)
    app = _proxy_app(settings)
    app.ui_config_path = tmp_path / "config.ui.toml"
    order: list[str] = []
    runtime = _FakeRuntime(order)
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
        app.personal_proxy = runtime
        transport = live_console.transport
        port = urlsplit(window.loaded_urls[0]).port
        live_console.api.set_loop(asyncio.get_running_loop())
        base = f"http://127.0.0.1:{port}"
        token = f"token={transport.token}"
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"{base}/api/journal/context/new?{token}", json={}
                )
                seen["new_context"] = (response.status, await response.json())
                response = await session.post(
                    f"{base}/api/journal/input?{token}", json={"text": "Привет"}
                )
                seen["input"] = (response.status, await response.json())
                form = aiohttp.FormData()
                form.add_field("text", "")
                form.add_field("files", b"data", filename="a.txt")
                response = await session.post(
                    f"{base}/api/journal/input?{token}", data=form
                )
                seen["attachment"] = (response.status, await response.json())
            seen["snapshot"] = transport.state.snapshot()["run_mode"]
            seen["proxy_status"] = transport.state.snapshot()["proxy_status"]
        finally:
            await transport.stop()

    monkeypatch.setattr(main_module, "build_app", fake_build_app)
    monkeypatch.setattr(main_module, "StatusConsoleWindow", lambda: window)
    monkeypatch.setattr(main_module, "run", fake_run)
    monkeypatch.setitem(
        sys.modules, "webview", types.SimpleNamespace(start=lambda start: start())
    )

    main_module.run_with_status_console(
        settings=settings, include_touchstrip=False, run_mode=RunMode.PERSONAL_PROXY
    )

    assert seen["built_for"] is RunMode.PERSONAL_PROXY
    assert seen["run_mode"] is RunMode.PERSONAL_PROXY
    assert seen["snapshot"]["mode"] == "personal_proxy"
    assert seen["proxy_status"] == {
        "dry_run": settings.personal_proxy.dry_run,
        "last_block": None,
    }
    assert "toggle_thinking" in seen["snapshot"]["refused"]
    assert "journal_input" not in seen["snapshot"]["refused"]
    assert seen["new_context"] == (
        200,
        {"status": "ok", "session_id": None, "provenance": None},
    )
    assert runtime.new_sessions == 1
    assert seen["input"][0] == 200
    assert runtime.texts == ["Привет"]
    assert seen["attachment"] == (
        409,
        {"status": "rejected", "reason": "attachments_unavailable"},
    )
    assert app.backend.calls == []


async def test_new_context_in_the_proxy_starts_a_proxy_session_and_not_a_model_context(
    tmp_path,
):
    app = _proxy_app(_settings(tmp_path))
    runtime = _FakeRuntime([])
    app.personal_proxy = runtime
    app.orchestrator.start_new_context = _must_not_be_called

    result = await new_context_handler_for(app, RunMode.PERSONAL_PROXY)()

    assert result.reason is NewContextReason.ACCEPTED
    assert runtime.new_sessions == 1
    assert app.backend.calls == []


async def test_new_context_in_the_proxy_leaves_the_history_of_the_main_model_alone(
    tmp_path,
):
    app = _proxy_app(_settings(tmp_path))
    app.personal_proxy = _FakeRuntime([])
    app.history.add("user", "u")
    turns_before = app.history.turns()

    await new_context_handler_for(app, RunMode.PERSONAL_PROXY)()

    assert app.history.turns() == turns_before


async def test_new_context_before_the_proxy_is_up_is_unavailable(tmp_path):
    app = _proxy_app(_settings(tmp_path))
    app.orchestrator.start_new_context = _must_not_be_called

    result = await new_context_handler_for(app, RunMode.PERSONAL_PROXY)()

    assert result.reason is NewContextReason.UNAVAILABLE


def test_new_context_in_a_normal_run_stays_the_orchestrators_own_action(tmp_path):
    app = _proxy_app(_settings(tmp_path))

    handler = new_context_handler_for(app, RunMode.NORMAL)

    assert handler == app.orchestrator.start_new_context


async def _must_not_be_called():
    raise AssertionError("the main model context must not be touched")


async def test_the_main_models_controls_never_reach_it_through_the_bus(tmp_path):
    app = _proxy_app(_settings(tmp_path))
    wire(app)
    bus: EventBus = app.bus

    await bus.publish(
        UtteranceChunk, UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)
    )

    assert app.backend.calls == []
    assert app.history.turns() == ()


async def test_run_refuses_debug_in_the_personal_proxy_before_anything_records(
    tmp_path, quiet_run
):
    settings = _settings(tmp_path)
    app = _proxy_app(settings)

    with pytest.raises(ValueError, match="debug"):
        await run(
            settings=settings,
            app=app,
            live_console=_console(),
            debug=True,
            run_mode=RunMode.PERSONAL_PROXY,
        )

    assert not recording()


async def test_no_exchange_is_recorded_for_a_check_request_in_the_personal_proxy(
    tmp_path, quiet_run, fake_hotkeys
):
    """The check backend goes through OllamaBackend.iter_chat, the one place the
    debug transcript is taken; in this mode it must have no sink."""
    from jarvis.core.debug_transcript import begin_exchange

    settings = _settings(tmp_path)
    app = _proxy_app(settings)
    order: list[str] = []
    seen: list[object] = []

    async def prepare(host):
        seen.append(begin_exchange({"messages": []}))
        return _FakeRuntime(order)

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: settings.hotkeys.shutdown in fake_hotkeys)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    assert seen == [None]


async def test_the_proxy_host_gets_the_apps_journal_recorder(
    tmp_path, quiet_run, fake_hotkeys
):
    settings = _settings(tmp_path)
    app = _proxy_app(settings)
    hosts: list[object] = []

    async def prepare(host):
        hosts.append(host)
        return _FakeRuntime([])

    running = _start_run(settings, app, fake_hotkeys, _console(), prepare)
    await _until(lambda: settings.hotkeys.shutdown in fake_hotkeys)
    fake_hotkeys[settings.hotkeys.shutdown]()
    await asyncio.wait_for(running, timeout=5)

    (host,) = hosts
    assert host.journal is app.journal_recorder
