import asyncio
import sys
import threading
import time
import types

import pytest

import jarvis.app as main_module
from jarvis.app import (
    create_live_status_console,
    unwire,
    wire_status_console,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    Settings,
)
from jarvis.dialog.response_mode import (
    ResponseMode,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
)
from jarvis.tools.host import (
    ToolEnablementChanged,
)
from jarvis.ui.contract import (
    RuntimeState,
    VisibilityMode,
)
from jarvis.ui.transport import UiTransportInfo
from tests.main_split._support_from_test_main import (
    _fake_app,
    _FakeStatusSurface,
    _FakeTransport,
)


def test_status_console_creates_windows_before_starting_pywebview(monkeypatch):
    journal_store = object()
    journal_search_index = object()
    journal_history_service = object()
    fake_app = types.SimpleNamespace(
        bus=EventBus(),
        thinking_mode=types.SimpleNamespace(level=ReasoningLevel.OFF),
        response_mode=types.SimpleNamespace(mode=ResponseMode.TEXT),
        visibility_mode=types.SimpleNamespace(mode=VisibilityMode.OPEN),
        tts_mute_state=None,
        solo_session_state=None,
        orchestrator=types.SimpleNamespace(
            submit_text_input=object(),
            on_attachment_submission=object(),
            start_new_context=object(),
            fork_from_journal_session=object(),
        ),
        journal_recorder=types.SimpleNamespace(session_id=None),
        journal_store=journal_store,
        journal_search_index=journal_search_index,
        history_projection_lifecycle=None,
        journal_history_service=journal_history_service,
        transcript_overlay_repository=object(),
        transcription_service=object(),
        annotation_overlay_repository=object(),
        annotation_generation_service=object(),
        consolidation_planner=object(),
        consolidation_executor=object(),
        memory_file_repository=object(),
    )

    class _FakeTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def start(self) -> object:
            return object()

    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        windows_created=False,
        load_transport_urls=lambda info: None,
    )

    def create_windows() -> None:
        fake_live_console.windows_created = True

    fake_live_console.create_windows = create_windows
    monkeypatch.setattr(main_module, "build_app", lambda settings: fake_app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeTransportServer)

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, app, live_console

    monkeypatch.setattr(main_module, "run", fake_run)

    def start(callback) -> None:
        assert fake_live_console.windows_created is True
        # The real pywebview always runs its func argument; a fake that
        # never does would deadlock the engine-completion future
        # run_with_status_console() now blocks on.
        callback()

    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(start=start))

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)


def test_status_console_transport_receives_journal_read_services(monkeypatch):
    app = _fake_app()
    captured_kwargs = {}

    class _FakeUiTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args
            captured_kwargs.update(kwargs)

        async def start(self) -> object:
            return object()

    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        create_windows=lambda: None,
        load_transport_urls=lambda info: None,
    )
    monkeypatch.setattr(main_module, "build_app", lambda settings: app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeUiTransportServer)

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, app, live_console

    monkeypatch.setattr(main_module, "run", fake_run)
    # The real pywebview always runs its func argument; a fake that never
    # does would deadlock the engine-completion future.
    monkeypatch.setitem(
        sys.modules,
        "webview",
        types.SimpleNamespace(start=lambda callback: callback()),
    )

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)

    assert captured_kwargs["journal_history_service"] is app.journal_history_service


def test_status_console_starts_history_lifecycle_before_transport(monkeypatch):
    app = _fake_app()
    calls: list[str] = []

    class _FakeLifecycle:
        def __init__(self) -> None:
            self.start_calls = 0
            self.started = False

        async def start(self) -> None:
            self.start_calls += 1
            if self.started:
                return
            self.started = True
            calls.append("lifecycle")

    class _FakeUiTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def start(self) -> object:
            calls.append("transport")
            return object()

    lifecycle = _FakeLifecycle()
    app.history_projection_lifecycle = lifecycle
    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        create_windows=lambda: None,
        load_transport_urls=lambda info: None,
    )
    monkeypatch.setattr(main_module, "build_app", lambda settings: app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeUiTransportServer)

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, live_console
        await main_module._start_history_projection_lifecycle(app)
        calls.append("run")

    monkeypatch.setattr(main_module, "run", fake_run)
    monkeypatch.setitem(
        sys.modules,
        "webview",
        types.SimpleNamespace(start=lambda callback: callback()),
    )

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)

    assert calls == ["lifecycle", "transport", "run"]
    assert lifecycle.start_calls == 2


def _patch_status_console_composition(monkeypatch, app, fake_run) -> None:
    """Shared fixture shape for run_with_status_console() lifecycle tests:
    fake every collaborator except the engine-completion contract under
    test."""

    class _FakeTransportServer:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def start(self) -> object:
            return object()

    fake_live_console = types.SimpleNamespace(
        api=object(),
        transport=None,
        create_windows=lambda: None,
        load_transport_urls=lambda info: None,
    )
    monkeypatch.setattr(main_module, "build_app", lambda settings: app)
    monkeypatch.setattr(
        main_module,
        "create_live_status_console",
        lambda app, include_touchstrip: fake_live_console,
    )
    monkeypatch.setattr(main_module, "UiTransportServer", _FakeTransportServer)
    monkeypatch.setattr(main_module, "run", fake_run)


def test_run_with_status_console_waits_for_a_delayed_engine_callback(monkeypatch):
    """pywebview's start() runs its func in a plain thread it never joins
    (verified against pywebview 6.2.1 source), and can return - GUI loop
    over - before that thread has even been scheduled. Returning to
    main() at that point starts interpreter shutdown that races the
    engine teardown (the shutdown executor-race bug report's root cause).
    run_with_status_console() must block on the engine's own completion,
    not on thread bookkeeping."""
    app = _fake_app()
    engine_finished = threading.Event()

    async def fake_run(settings=None, app=None, live_console=None, debug=False) -> None:
        del settings, app, live_console
        await asyncio.sleep(0.05)
        engine_finished.set()

    _patch_status_console_composition(monkeypatch, app, fake_run)

    def gui_start_without_join(callback) -> None:
        def delayed_callback() -> None:
            # The callback has not even started when start() returns.
            time.sleep(0.15)
            callback()

        threading.Thread(target=delayed_callback).start()

    monkeypatch.setitem(
        sys.modules, "webview", types.SimpleNamespace(start=gui_start_without_join)
    )

    main_module.run_with_status_console(settings=Settings(), include_touchstrip=False)

    assert engine_finished.is_set()


def test_run_with_status_console_reraises_an_engine_callback_failure(monkeypatch):
    """An exception that kills the engine must reach
    run_with_status_console()'s caller, not die silently in pywebview's
    unjoined thread."""
    app = _fake_app()

    async def failing_run(
        settings=None, app=None, live_console=None, debug=False
    ) -> None:
        del settings, app, live_console
        raise RuntimeError("engine exploded")

    _patch_status_console_composition(monkeypatch, app, failing_run)

    def gui_start_without_join(callback) -> None:
        threading.Thread(target=callback).start()

    monkeypatch.setitem(
        sys.modules, "webview", types.SimpleNamespace(start=gui_start_without_join)
    )

    with pytest.raises(RuntimeError, match="engine exploded"):
        main_module.run_with_status_console(
            settings=Settings(), include_touchstrip=False
        )


def test_push_runtime_state_is_not_suppressed_by_a_direct_transport_update():
    from jarvis.app import LiveStatusConsole, _push_runtime_state

    surface = _FakeStatusSurface()
    transport = _FakeTransport()
    live_console = LiveStatusConsole(
        console=surface, touchstrip=None, api=object(), transport=transport
    )

    transport.set_runtime_state(RuntimeState.SPEAKING, "Произношу ответ...")
    _push_runtime_state(live_console, RuntimeState.THINKING, "Обрабатываю голос...")
    _push_runtime_state(live_console, RuntimeState.LISTENING, "Готов слушать")

    assert transport.calls == [
        ("runtime", (RuntimeState.SPEAKING, "Произношу ответ...")),
        ("runtime", (RuntimeState.THINKING, "Обрабатываю голос...")),
        ("runtime", (RuntimeState.LISTENING, "Готов слушать")),
    ]


def test_desktop_console_native_close_is_wired_to_shutdown_request():
    app = _fake_app()
    console = _FakeStatusSurface()
    touchstrip = _FakeStatusSurface()

    live_console = create_live_status_console(
        app, console=console, touchstrip=touchstrip, include_touchstrip=True
    )

    live_console.transport = _FakeTransport()
    transport_info = UiTransportInfo(host="127.0.0.1", port=4321, token="token")
    live_console.create_windows()
    live_console.load_transport_urls(transport_info)

    assert console.created_with_on_closed == live_console.api.request_shutdown
    assert console.loaded_url.endswith("/?token=token")
    assert touchstrip.loaded_url.endswith("/touchstrip.html?token=token")


async def test_wire_status_console_repaints_tool_rows_after_a_toggle():
    """A toggle already moved the checkbox in the browser, so the engine
    republishes the whole tool state - the row must never keep a label
    the engine no longer holds."""
    app = _fake_app()
    live_console = create_live_status_console(app, include_touchstrip=False)
    transport = _FakeTransport()
    live_console.transport = transport
    subscriptions = wire_status_console(app, live_console, asyncio.get_running_loop())

    await app.bus.publish(ToolEnablementChanged, ToolEnablementChanged())

    kind, payload = transport.calls[-1]
    assert kind == "mcp"
    assert [tool["name"] for tool in payload["local_tools"]] == [
        "capture_camera_image",
        "list_session_files",
        "read_history",
        "read_history_ranges",
        "read_session_text",
        "remember",
        "search_history",
        "set_reasoning_level",
        "stat_session_file",
        "view_session_image",
        "write_session_file",
    ]
    unwire(app, subscriptions)
