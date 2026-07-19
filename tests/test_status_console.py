import asyncio
import logging

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    McpSettings,
    PiperTtsSettings,
    Settings,
    SileroTtsSettings,
    VadSettings,
    load_settings,
)
from jarvis.core.lifecycle import ModelRequestInput
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
    ReasoningLevelState,
)
from jarvis.journal import JournalEvent, JournalStore
from jarvis.tools.host import McpModuleStatus
from jarvis.tools.registry import RegisteredTool, ToolRegistry
from jarvis.ui.contract import (
    DataLocality,
    DataSource,
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
from jarvis.ui.status_console import (
    INDEX_HTML,
    UI_DIR,
    MicrophoneOptionsAvailable,
    ModelOptionsAvailable,
    StatusConsoleApi,
    StatusConsoleWindow,
    UiConfigSaved,
    _journal_session_title,
    data_locality_payload,
    data_source_payload,
    mcp_state_payload,
    model_request_payload,
    module_health_payload,
    options_payload,
    runtime_state_payload,
    system_event_payload,
    thinking_mode_payload,
    visibility_mode_payload,
)
from jarvis.ui.visibility import VisibilityModeState

logger = logging.getLogger("test_status_console")


@pytest.mark.parametrize("state", list(RuntimeState))
def test_runtime_state_payload_covers_every_contract_state(state):
    payload = runtime_state_payload(state)

    assert payload["state"] == state.value
    assert payload["label"]  # every state has a non-empty label
    assert "substatus" in payload


def test_runtime_state_payload_uses_given_substatus_over_the_default():
    payload = runtime_state_payload(
        RuntimeState.ERROR, substatus="TTS: device not found"
    )

    assert payload["substatus"] == "TTS: device not found"


def test_blank_context_session_title_is_not_voice_fallback(tmp_path):
    session_id = "20260719-100000-ab12"
    store = JournalStore(tmp_path)
    store.append(
        JournalEvent(
            session_id=session_id,
            timestamp="2026-07-19T10:00:00+01:00",
            source="context",
            role="system",
            text="New blank context started by user.",
            media=[],
            transcript=None,
            metadata={"kind": "new_context"},
        )
    )

    assert _journal_session_title(session_id, store) == "New context"


def test_module_health_payload_shape():
    health = ModuleHealth(
        module=ModuleId.TTS, status=HealthStatus.DEGRADED, detail="slow"
    )

    assert module_health_payload(health) == {
        "module": "tts",
        "status": "degraded",
        "detail": "slow",
    }


def test_data_locality_payload_shape():
    assert data_locality_payload(DataLocality.EXTERNAL) == {"locality": "external"}


def test_data_source_payload_shape():
    assert data_source_payload(DataSource.INTERNET) == {"source": "internet"}


def test_mcp_state_payload_zeros_tools_when_off_and_marks_live_tools_available():
    tools = (RegisteredTool("web_search", "Search", {}, "search", enabled=True),)

    assert mcp_state_payload(McpModuleStatus.OFF, tools) == {
        "status": "off",
        "enabled": False,
        "tools": [],
    }
    assert mcp_state_payload(McpModuleStatus.DEGRADED, tools) == {
        "status": "degraded",
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


def test_model_request_payload_shape_contains_only_metadata():
    assert model_request_payload(
        ModelRequestSummary(
            timestamp=123.0,
            items=(
                ModelRequestItem(ModelRequestInput.AUDIO, audio_duration_seconds=4.25),
                ModelRequestItem(ModelRequestInput.SCREENSHOT),
            ),
        )
    ) == {
        "timestamp": 123.0,
        "items": [
            {"kind": "audio", "duration_seconds": 4.25},
            {"kind": "screenshot"},
        ],
    }


def test_system_event_payload_shape():
    event = SystemEvent(
        timestamp=1234.5,
        source="WARMUP",
        level=EventLevel.WARN,
        message="слишком долго",
    )

    assert system_event_payload(event) == {
        "timestamp": 1234.5,
        "source": "WARMUP",
        "level": "warn",
        "message": "слишком долго",
        "correlation_id": None,
    }


def test_visibility_mode_payload_shape():
    assert visibility_mode_payload(VisibilityMode.HIDDEN) == {"mode": "hidden"}


@pytest.mark.parametrize(
    "level,expected_is_enabled",
    [
        (ReasoningLevel.OFF, False),
        (ReasoningLevel.LOW, True),
        (ReasoningLevel.MEDIUM, True),
        (ReasoningLevel.HIGH, True),
    ],
)
def test_thinking_mode_payload_carries_level_and_derived_is_enabled(
    level, expected_is_enabled
):
    assert thinking_mode_payload(level) == {
        "level": level.value,
        "is_enabled": expected_is_enabled,
    }


# --- StatusConsoleApi (task-ui-04: JS -> Python bridge) ---------------------


class _FakeHistory:
    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


class _FakeMcpHost:
    def __init__(self) -> None:
        self.status = McpModuleStatus.OFF
        self.registry = ToolRegistry()

    @property
    def enabled(self) -> bool:
        return self.status in {McpModuleStatus.ON, McpModuleStatus.DEGRADED}

    async def enable(self) -> None:
        self.status = McpModuleStatus.DEGRADED

    async def disable(self) -> None:
        self.status = McpModuleStatus.OFF


@pytest.mark.asyncio
async def test_mcp_control_applies_live_then_persists_authoritative_state(tmp_path):
    bus = EventBus()
    host = _FakeMcpHost()
    ui_config_path = tmp_path / "config.ui.toml"
    api = StatusConsoleApi(
        thinking_mode=ReasoningLevelState(bus=bus),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        loop=asyncio.get_running_loop(),
        settings=Settings(mcp=McpSettings(enabled=False)),
        ui_config_path=ui_config_path,
        mcp_host=host,
    )

    api.set_mcp_enabled(True)
    await asyncio.sleep(0.05)

    assert host.status is McpModuleStatus.DEGRADED
    contents = ui_config_path.read_text(encoding="utf-8")
    assert "[mcp]\nenabled = true" in contents
    assert "[backend]" not in contents
    assert "[microphone]" not in contents
    assert "[ui]" not in contents
    assert "[vad]" not in contents
    assert "[tts" not in contents
    assert (
        load_settings(
            tmp_path / "does-not-exist.toml", ui_path=ui_config_path
        ).mcp.enabled
        is True
    )

    api.set_mcp_enabled(False)
    await asyncio.sleep(0.05)

    assert host.status is McpModuleStatus.OFF
    assert (
        load_settings(
            tmp_path / "does-not-exist.toml", ui_path=ui_config_path
        ).mcp.enabled
        is False
    )


async def test_api_methods_are_a_no_op_before_set_loop_is_called():
    """Chicken-and-egg ordering (see StatusConsoleApi's docstring):
    the control client may send a command before the real asyncio loop exists.
    Nothing should raise, and nothing should happen,
    until set_loop() runs."""
    thinking_mode = ReasoningLevelState(bus=EventBus())
    api = StatusConsoleApi(
        thinking_mode=thinking_mode,
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    api.toggle_thinking()
    api.set_reasoning_level("high")
    api.reset_context()
    api.reset_module("backend")
    api.request_shutdown()
    await asyncio.sleep(0.05)

    assert thinking_mode.level is ReasoningLevel.OFF


@pytest.mark.parametrize(
    ("method_name", "bad_value"),
    [
        ("set_reasoning_level", "max"),
        ("reset_module", "not-a-real-module"),
        ("set_visibility_mode", "invisible"),
    ],
)
async def test_direct_call_with_an_unknown_value_raises_value_error(
    method_name, bad_value
):
    """task-v1.5.1-2: the old "log a warning and silently return" guard
    carried a stale justification (the pywebview js_api bridge removed in
    v1.2.10). The WS control path rejects unknown values one layer up as
    a ProtocolError (see test_ui_transport.py); a direct programmatic
    call now fails loudly instead of silently doing nothing."""
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    with pytest.raises(ValueError):
        getattr(api, method_name)(bad_value)


def test_api_methods_are_a_safe_no_op_after_the_loop_has_closed():
    """Regression for a real live-session bug (2026-07-07): after a
    successful shutdown, a duplicate UI call can still race with the
    already-closed asyncio loop. This used to crash with "RuntimeError:
    Event loop is closed" raised synchronously inside pywebview's own
    dispatch thread (call_soon_threadsafe() -> _check_closed()), at the
    time reachable through the since-removed js_api bridge. The guard is
    still required: pywebview's GUI thread calls request_shutdown()
    directly via the window's native on_closed hook (task-v1.5.1-2
    resolution), and that path must never raise into pywebview. No await
    here: everything must return immediately without ever touching the
    closed loop."""
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    thinking_mode = ReasoningLevelState(bus=EventBus())
    api = StatusConsoleApi(
        thinking_mode=thinking_mode,
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
        loop=closed_loop,
        shutdown_event=asyncio.Event(),
    )

    api.toggle_thinking()
    api.set_reasoning_level("high")
    api.reset_context()
    api.reset_module("backend")
    api.set_visibility_mode("open")
    api.request_shutdown()
    api.request_model_options()
    api.request_microphone_options()
    api.save_config_selection("model", "device")

    assert thinking_mode.level is ReasoningLevel.OFF


async def test_toggle_thinking_schedules_a_real_toggle_after_set_loop():
    bus = EventBus()
    thinking_mode = ReasoningLevelState(bus=bus)
    api = StatusConsoleApi(
        thinking_mode=thinking_mode,
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )
    api.set_loop(asyncio.get_running_loop())

    api.toggle_thinking()
    await asyncio.sleep(0.05)

    assert thinking_mode.level is ReasoningLevel.LOW


@pytest.mark.parametrize(
    "trigger",
    ["toggle_thinking", "set_reasoning_level"],
)
async def test_status_console_api_reasoning_level_changes_are_tagged_ui_not_hotkey(
    trigger,
):
    """Regression (live human check, 2026-07-13): both StatusConsoleApi
    entry points - the touchstrip/compat cycle and Control Center's direct
    selection - go through this API, never through the global hotkey, so
    the resulting event must carry source="UI", not the hotkey's tag."""
    bus = EventBus()
    thinking_mode = ReasoningLevelState(bus=bus)
    received: list[ReasoningLevelChanged] = []

    async def on_event(event: ReasoningLevelChanged) -> None:
        received.append(event)

    bus.subscribe(ReasoningLevelChanged, on_event)
    api = StatusConsoleApi(
        thinking_mode=thinking_mode,
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )
    api.set_loop(asyncio.get_running_loop())

    if trigger == "toggle_thinking":
        api.toggle_thinking()
    else:
        api.set_reasoning_level("medium")
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].source == "UI"


async def test_reset_context_clears_history_and_publishes_an_info_event():
    bus = EventBus()
    received: list[SystemEvent] = []

    async def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(SystemEvent, on_event)
    history = _FakeHistory()
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=history,
        bus=bus,
        logger=logger,
    )

    api.reset_context()
    await asyncio.sleep(0.05)

    assert history.cleared is True
    assert len(received) == 1
    assert received[0].level is EventLevel.INFO


@pytest.mark.parametrize("module", list(ModuleId))
async def test_reset_module_never_claims_success_and_reports_a_warn_event(module):
    bus = EventBus()
    received: list[SystemEvent] = []

    async def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(SystemEvent, on_event)
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
    )

    api.reset_module(module.value)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].level is EventLevel.WARN
    assert "успеш" not in received[0].message.lower()


async def test_set_visibility_mode_changes_state_and_publishes_a_system_event():
    bus = EventBus()
    received: list[SystemEvent] = []

    async def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(SystemEvent, on_event)
    visibility_mode = VisibilityModeState(bus=bus)
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        visibility_mode=visibility_mode,
    )

    api.set_visibility_mode("hidden")
    await asyncio.sleep(0.05)

    assert visibility_mode.mode is VisibilityMode.HIDDEN
    assert len(received) == 1
    assert received[0].level is EventLevel.INFO


async def test_set_visibility_mode_to_the_current_mode_does_not_publish():
    bus = EventBus()
    received: list[SystemEvent] = []

    async def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(SystemEvent, on_event)
    visibility_mode = VisibilityModeState(bus=bus)  # starts OPEN
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        visibility_mode=visibility_mode,
    )

    api.set_visibility_mode("open")  # already OPEN
    await asyncio.sleep(0.05)

    assert received == []


@pytest.mark.parametrize(
    "level_value,expected_level",
    [
        ("off", ReasoningLevel.OFF),
        ("low", ReasoningLevel.LOW),
        ("medium", ReasoningLevel.MEDIUM),
        ("high", ReasoningLevel.HIGH),
    ],
)
async def test_set_reasoning_level_accepts_every_product_value(
    level_value, expected_level
):
    thinking_mode = ReasoningLevelState(bus=EventBus())
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=thinking_mode,
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    api.set_reasoning_level(level_value)
    await asyncio.sleep(0.05)

    assert thinking_mode.level is expected_level


async def test_set_reasoning_level_with_unknown_value_does_not_change_state():
    """The real protocol-error rejection for an unknown level happens one
    layer up, in UiTransportServer._set_reasoning_level() (see
    test_ui_transport.py) - a WS client gets a ProtocolError, not a silent
    no-op. Since task-v1.5.1-2, a direct call with a bad value raises
    ValueError (the old silent warn-and-return guard carried a stale
    pywebview-bridge justification); either way, engine state must not
    change."""
    thinking_mode = ReasoningLevelState(bus=EventBus())
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=thinking_mode,
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    with pytest.raises(ValueError):
        api.set_reasoning_level("max")  # not a supported product value
    await asyncio.sleep(0.05)

    assert thinking_mode.level is ReasoningLevel.OFF


async def test_hotkey_cycle_after_a_direct_control_center_selection_continues_from_it():
    """story-v1.3.1 task 3 acceptance criterion: Control Center's
    set_reasoning_level and the global hotkey's cycle_level() share one
    ReasoningLevelState (constructed once in build_app()'s composition
    root), so a hotkey cycle right after a direct selection must continue
    the off -> low -> medium -> high -> off order from the selected level,
    not from wherever the hotkey last left off. The hotkey callback itself
    only ever calls cycle_level() (see run_hotkey_listener) - exercised
    directly here rather than through a fake keyboard provider, since that
    binding is already covered by test_thinking_mode.py."""
    thinking_mode = ReasoningLevelState(bus=EventBus())
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=thinking_mode,
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    api.set_reasoning_level("medium")
    await asyncio.sleep(0.05)
    assert thinking_mode.level is ReasoningLevel.MEDIUM

    await thinking_mode.cycle_level(
        source="HOTKEY"
    )  # what the hotkey callback triggers

    assert thinking_mode.level is ReasoningLevel.HIGH


async def test_request_shutdown_sets_the_given_event_and_publishes_an_info_event():
    bus = EventBus()
    received: list[SystemEvent] = []

    async def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(SystemEvent, on_event)
    shutdown_event = asyncio.Event()
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        shutdown_event=shutdown_event,
    )

    api.request_shutdown()
    await asyncio.sleep(0.05)

    assert shutdown_event.is_set()
    assert len(received) == 1
    assert received[0].level is EventLevel.INFO


async def test_set_shutdown_event_wires_up_a_previously_unset_api():
    """Mirrors set_loop()'s own chicken-and-egg ordering test: main.py's
    real StatusConsoleApi is constructed (create_live_status_console())
    before run() creates the real shutdown_event, so set_shutdown_event()
    must be able to wire it up after construction, not only via the
    constructor kwarg."""
    shutdown_event = asyncio.Event()
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    api.set_shutdown_event(shutdown_event)
    api.request_shutdown()
    await asyncio.sleep(0.05)

    assert shutdown_event.is_set()


async def test_request_shutdown_is_a_no_op_without_a_shutdown_event_even_with_a_loop():
    """set_loop() alone is not enough - request_shutdown() must not raise
    or silently swallow the request if set_shutdown_event() was never
    called (e.g. a live_console built without going through main.py's
    run()); it must simply do nothing, the same "no-op until fully wired"
    rule set_loop()'s own docstring already promises for every method."""
    shutdown_event_never_set = asyncio.Event()
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    api.request_shutdown()
    await asyncio.sleep(0.05)

    assert shutdown_event_never_set.is_set() is False


def test_index_html_has_no_hardcoded_model_name():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "gemma" not in html.lower()


def test_index_html_has_no_google_fonts_or_cdn_reference():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_style_css_has_no_network_loaded_assets():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")

    assert "@import" not in css
    assert "http://" not in css
    assert "https://" not in css


def test_style_css_gives_warming_a_distinct_color_from_error_and_speaking():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")

    def live_color_for(state: str) -> str:
        marker = f'html[data-state="{state}"]'
        start = css.index(marker)
        line_end = css.index("}", start)
        rule = css[start:line_end]
        color_start = rule.index("--live:") + len("--live:")
        return rule[color_start : rule.index(";", color_start)].strip()

    warming_color = live_color_for("warming")
    error_color = live_color_for("error")
    speaking_color = live_color_for("speaking")

    assert warming_color != error_color
    assert warming_color != speaking_color


def test_style_css_has_a_narrow_width_media_query():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")

    assert "@media" in css
    assert "grid-template-areas" in css.split("@media", 1)[1]


def test_app_js_clears_module_detail_when_payload_detail_is_empty():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert 'const detail = module === "backend" && _modelLabel ? ' in js
    assert "meta.textContent = _moduleDetail(module, detail);" in js
    assert "if (payload.detail)" not in js


def test_index_html_has_a_real_events_panel_not_a_placeholder():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="logList"' in html
    assert "task-ui-03" not in html


def test_app_js_caps_the_number_of_rendered_log_entries():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "MAX_LOG_ENTRIES" in js
    assert "while (list.children.length > MAX_LOG_ENTRIES)" in js
    assert "list.removeChild(list.lastChild)" in js


def test_style_css_gives_error_and_warn_log_levels_distinct_colors():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")

    def color_for_level(level: str) -> str:
        marker = f'.log-entry[data-level="{level}"] .log-msg'
        start = css.index(marker)
        rule_start = css.index("{", start)
        rule_end = css.index("}", rule_start)
        rule = css[rule_start:rule_end]
        color_start = rule.index("color:") + len("color:")
        return rule[color_start : rule.index(";", color_start)].strip()

    assert color_for_level("warn") != color_for_level("error")


def test_index_html_has_a_real_reasoning_level_toggle_not_a_disabled_placeholder():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="reasoningLevelToggle"' in html
    for level in ("off", "low", "medium", "high"):
        assert f'data-level="{level}"' in html
        assert f"setReasoningLevel('{level}')" in html
    assert "task-ui-04" not in html
    assert "placeholder-switch" not in html
    # Scoped to the think-card block, not the whole page: story-v1.2.4-
    # task-3's Apply button is legitimately disabled elsewhere until its
    # dropdowns actually load (a real fix, not a placeholder leftover) -
    # a blanket "disabled" not in html check would misfire on that.
    think_card_start = html.index('<div class="think-card">')
    action_row_start = html.index('<div class="action-row">', think_card_start)
    think_card_html = html[think_card_start:action_row_start]
    assert "disabled" not in think_card_html


def test_reasoning_level_toggle_has_no_optimistic_initial_selection():
    """Stop condition: 'UI controls can become selected before authoritative
    state arrives'. Reopening the Status Console while Jarvis keeps running
    at a non-off level must not flash "Off" as selected before the real
    snapshot corrects it - so the static markup must not preselect any
    button; applyThinkingMode() is the only thing that ever adds "sel"."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    toggle_start = html.index('id="reasoningLevelToggle"')
    toggle_end = html.index("</div>", toggle_start)
    toggle_html = html[toggle_start:toggle_end]
    assert "sel" not in toggle_html


def test_set_reasoning_level_sends_the_control_command_with_the_clicked_level():
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "function setReasoningLevel(levelValue)" in app_js
    assert '_sendControl("set_reasoning_level", { level: levelValue })' in app_js


def test_desktop_reasoning_level_selection_updates_only_from_the_payload():
    """task 4 item 3 / stop condition: never optimistic on click - the
    selected button changes only inside applyThinkingMode(), driven by the
    authoritative snapshot/delta, not inside setReasoningLevel()'s click
    handler itself."""
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    set_level_start = app_js.index("function setReasoningLevel(")
    set_level_end = app_js.index("\n}\n", set_level_start)
    assert "classList" not in app_js[set_level_start:set_level_end]

    assert "REASONING_LEVELS.includes(payload.level)" in app_js
    assert "button.dataset.level === payload.level" in app_js


def test_modules_panel_is_rendered_from_the_shared_module_contract():
    html = INDEX_HTML.read_text(encoding="utf-8")
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="modulesPanel"' in html
    assert 'id="chip-backend"' not in html
    assert "for (const module of MODULE_IDS)" in app_js
    assert 'status: "unavailable"' in app_js


def test_last_model_request_panel_renders_the_timestamp_before_metadata():
    html = INDEX_HTML.read_text(encoding="utf-8")
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="lastRequestList"' in html
    assert "function applyLastModelRequest(payload)" in app_js
    assert 'formatLogTime(payload.timestamp) + " - "' in app_js
    assert 'uiString("last_request_" + item.kind)' in app_js


def test_status_console_does_not_render_the_observed_input_panel():
    html = INDEX_HTML.read_text(encoding="utf-8")
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "dataPresenceList" not in html
    assert "applyDataPresence" not in app_js


def test_index_html_global_reset_requires_confirmation_before_the_api_call():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="confirmRow"' in html
    assert "showResetConfirm()" in html
    assert "confirmContextReset()" in html


def test_index_html_uses_open_hidden_labels_not_the_old_ones():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert ">Open<" in html
    assert ">Hidden<" in html
    assert "Приватно" not in html
    assert "На людях" not in html
    assert "task-ui-05" not in html


def test_app_js_visibility_mode_never_touches_the_locality_badge():
    """task-ui-05 AC: 'Hidden does not imply cloud/offline status' - data
    locality and visibility mode must stay structurally independent, not
    just independent by convention."""
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    apply_visibility_start = js.index("function applyVisibilityMode")
    apply_visibility_end = js.index("\n}\n", apply_visibility_start)
    body = js[apply_visibility_start:apply_visibility_end]
    code_lines = [
        line for line in body.splitlines() if not line.strip().startswith("//")
    ]
    code_only = "\n".join(code_lines)

    assert 'getElementById("localityBadge")' not in code_only
    assert "applyDataLocality(" not in code_only


def test_style_css_hidden_uses_violet_not_amber():
    """Amber is reserved for warning/cloud/warmup-adjacent per
    tasks/task-ui-privacy-and-touchstrip-requirements.md - Hidden must not
    look like a cloud/error state."""
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")

    marker = '.visibility-toggle button.sel[data-mode="hidden"]'
    start = css.index(marker)
    rule = css[start : css.index("}", start)]

    assert "var(--violet)" in rule
    assert "var(--amber)" not in rule


# --- story-v1.2.4-task-3: configuration menu (model/microphone) ------------


def test_options_payload_shape():
    assert options_payload(["a", "b"], "a") == {"options": ["a", "b"], "current": "a"}


async def test_request_model_options_publishes_current_plus_fetched_options():
    bus = EventBus()
    received: list[ModelOptionsAvailable] = []

    async def on_event(event: ModelOptionsAvailable) -> None:
        received.append(event)

    bus.subscribe(ModelOptionsAvailable, on_event)

    async def fake_source() -> list[str]:
        return ["model-a", "model-b"]

    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        settings=Settings(),  # default backend.model is not in fake_source()'s list
        model_options_source=fake_source,
    )

    api.request_model_options()
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].current == Settings().backend.model
    assert received[0].options == [Settings().backend.model, "model-a", "model-b"]


async def test_request_model_options_degrades_to_current_value_on_failure():
    """AC: 'Source failure degrades each selector to the current
    configured value' - never live Ollama in a pure test, so the
    injectable source simply raises to simulate a real network failure."""
    bus = EventBus()
    received: list[ModelOptionsAvailable] = []
    system_events: list[SystemEvent] = []

    async def on_options(event: ModelOptionsAvailable) -> None:
        received.append(event)

    async def on_system_event(event: SystemEvent) -> None:
        system_events.append(event)

    bus.subscribe(ModelOptionsAvailable, on_options)
    bus.subscribe(SystemEvent, on_system_event)

    async def failing_source() -> list[str]:
        raise ConnectionError("Ollama unreachable")

    settings = Settings()
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        settings=settings,
        model_options_source=failing_source,
    )

    api.request_model_options()
    await asyncio.sleep(0.05)

    assert received == [
        ModelOptionsAvailable(
            options=[settings.backend.model], current=settings.backend.model
        )
    ]
    assert len(system_events) == 1
    assert system_events[0].level is EventLevel.WARN


async def test_request_microphone_options_publishes_current_plus_fetched_options():
    bus = EventBus()
    received: list[MicrophoneOptionsAvailable] = []

    async def on_event(event: MicrophoneOptionsAvailable) -> None:
        received.append(event)

    bus.subscribe(MicrophoneOptionsAvailable, on_event)

    async def fake_source() -> list[str]:
        return ["Built-in Microphone", "USB Headset"]

    settings = Settings()
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        settings=settings,
        microphone_options_source=fake_source,
    )

    api.request_microphone_options()
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].current == settings.microphone.device  # "" by default
    assert received[0].options == ["", "Built-in Microphone", "USB Headset"]


async def test_request_microphone_options_degrades_to_current_value_on_failure():
    bus = EventBus()
    received: list[MicrophoneOptionsAvailable] = []

    async def on_event(event: MicrophoneOptionsAvailable) -> None:
        received.append(event)

    bus.subscribe(MicrophoneOptionsAvailable, on_event)

    async def failing_source() -> list[str]:
        raise OSError("no PortAudio backend")

    settings = Settings()
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        settings=settings,
        microphone_options_source=failing_source,
    )

    api.request_microphone_options()
    await asyncio.sleep(0.05)

    assert received == [
        MicrophoneOptionsAvailable(
            options=[settings.microphone.device], current=settings.microphone.device
        )
    ]


async def test_save_config_selection_writes_only_ui_config_and_publishes_saved_event(
    tmp_path,
):
    bus = EventBus()
    saved_events: list[UiConfigSaved] = []
    system_events: list[SystemEvent] = []

    async def on_saved(event: UiConfigSaved) -> None:
        saved_events.append(event)

    async def on_system_event(event: SystemEvent) -> None:
        system_events.append(event)

    bus.subscribe(UiConfigSaved, on_saved)
    bus.subscribe(SystemEvent, on_system_event)

    ui_config_path = tmp_path / "config.ui.toml"
    base_config_path = tmp_path / "config.toml"
    base_config_path.write_text('[backend]\nmodel = "do-not-touch"\n', encoding="utf-8")

    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        ui_config_path=ui_config_path,
    )

    api.save_config_selection("new-model", "USB Headset")
    await asyncio.sleep(0.05)

    assert ui_config_path.exists()
    written = ui_config_path.read_text(encoding="utf-8")
    assert "new-model" in written
    assert "USB Headset" in written
    # never touched the base config.toml-shaped file
    assert (
        base_config_path.read_text(encoding="utf-8")
        == '[backend]\nmodel = "do-not-touch"\n'
    )
    assert len(saved_events) == 1
    assert len(system_events) == 1


@pytest.mark.parametrize("empty_model", ["", "   "])
async def test_save_config_selection_rejects_an_empty_model(tmp_path, empty_model):
    """Regression for a real live-session bug (2026-07-07): app.js's
    "Применить" button used to be clickable before either <select> ever
    received real options, reading modelSelect.value as "" and saving an
    empty backend.model that broke the next startup. app.js now disables
    the button until both selectors load (front-end guard); this is the
    Python-side backstop for any other caller that might not respect it -
    an empty model must never reach write_ui_config()."""
    bus = EventBus()
    saved_events: list[UiConfigSaved] = []
    system_events: list[SystemEvent] = []

    async def on_saved(event: UiConfigSaved) -> None:
        saved_events.append(event)

    async def on_system_event(event: SystemEvent) -> None:
        system_events.append(event)

    bus.subscribe(UiConfigSaved, on_saved)
    bus.subscribe(SystemEvent, on_system_event)

    ui_config_path = tmp_path / "config.ui.toml"
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        ui_config_path=ui_config_path,
    )

    api.save_config_selection(empty_model, "USB Headset")
    await asyncio.sleep(0.05)

    assert not ui_config_path.exists()
    assert saved_events == []
    assert len(system_events) == 1
    assert system_events[0].level is EventLevel.WARN


async def test_save_config_selection_allows_an_empty_microphone_device(tmp_path):
    """ "" is the legitimate system-default sentinel for microphone
    (MicrophoneSettings.device's own default) - only an empty model is
    ever rejected."""
    bus = EventBus()
    saved_events: list[UiConfigSaved] = []
    system_events: list[SystemEvent] = []

    async def on_saved(event: UiConfigSaved) -> None:
        saved_events.append(event)

    async def on_system_event(event: SystemEvent) -> None:
        system_events.append(event)

    bus.subscribe(UiConfigSaved, on_saved)
    bus.subscribe(SystemEvent, on_system_event)

    ui_config_path = tmp_path / "config.ui.toml"
    api = StatusConsoleApi(
        loop=asyncio.get_running_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        ui_config_path=ui_config_path,
    )

    api.save_config_selection("some-model", "")
    await asyncio.sleep(0.05)

    assert ui_config_path.exists()
    assert len(saved_events) == 1
    assert system_events[0].level is EventLevel.INFO


async def test_config_menu_methods_are_a_no_op_before_set_loop_is_called():
    api = StatusConsoleApi(
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=EventBus(),
        logger=logger,
    )

    api.request_model_options()
    api.request_microphone_options()
    api.save_config_selection("x", "y")
    await asyncio.sleep(0.05)  # nothing should raise or run


def test_index_html_has_a_real_config_menu_not_a_placeholder():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="modelSelect"' in html
    assert 'id="micSelect"' in html
    assert "toggleConfigMenu()" in html
    assert "applyConfigSelection()" in html
    assert "task-3" not in html


def test_index_html_groups_lower_controls_in_one_action_row():
    html = INDEX_HTML.read_text(encoding="utf-8")
    row_start = html.index('<div class="action-row">')
    config_panel_start = html.index('<div class="config-panel"', row_start)
    action_row = html[row_start:config_panel_start]

    assert action_row.index('id="btnConfigToggle"') < action_row.index(
        'id="btnResetGlobal"'
    )
    assert action_row.index('id="btnResetGlobal"') < action_row.index(
        'id="btnShutdown"'
    )


def test_style_css_action_row_is_centered_and_wraps_at_narrow_widths():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    marker = ".action-row {"
    start = css.index(marker)
    rule = css[start : css.index("}", start)]

    assert "display: flex" in rule
    assert "flex-wrap: nowrap" in rule
    assert "justify-content: center" in rule
    responsive_css = css[css.index("@media") :]
    assert ".action-row" in responsive_css
    assert "flex-wrap: wrap" in responsive_css


def test_index_html_keeps_confirmation_panels_below_the_action_row():
    html = INDEX_HTML.read_text(encoding="utf-8")
    row_start = html.index('<div class="action-row">')
    feedback_start = html.index('<div class="action-feedback">', row_start)
    action_row = html[row_start:feedback_start]

    assert 'id="confirmRow"' not in action_row
    assert 'id="shutdownConfirmRow"' not in action_row
    assert 'id="confirmRow"' in html[feedback_start:]
    assert 'id="shutdownConfirmRow"' in html[feedback_start:]


def test_style_css_confirmation_feedback_spans_the_action_area():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    feedback_start = css.index(".action-feedback {")
    feedback_rule = css[feedback_start : css.index("}", feedback_start)]
    confirm_start = css.index(".confirm-row {")
    confirm_rule = css[confirm_start : css.index("}", confirm_start)]

    assert "width: 100%" in feedback_rule
    assert "width: 100%" in confirm_rule


def test_status_console_default_height_allows_the_config_panel_to_open():
    captured: dict[str, object] = {}

    def window_factory(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    StatusConsoleWindow(window_factory=window_factory).create()

    assert captured["height"] == 900


def test_app_js_config_menu_refetches_options_only_when_opening_the_panel():
    """toggleConfigMenu() must not fetch on close - re-fetching only makes
    sense when the panel is becoming visible."""
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    start = js.index("function toggleConfigMenu")
    end = js.index("\n}\n", start)
    body = js[start:end]

    assert "if (!opening) return;" in body
    assert "request_model_options" in body
    assert "request_microphone_options" in body
    # Regression (2026-07-07): must re-arm the Apply button to disabled
    # on every open, not just leave whatever loaded state survived from
    # before - otherwise a fast reopen-then-click could apply stale/
    # not-yet-refreshed selections as if they were current.
    assert "_modelOptionsLoaded = false;" in body
    assert "_microphoneOptionsLoaded = false;" in body


def test_index_html_config_apply_button_starts_disabled():
    """Regression for a real live-session bug (2026-07-07): the Apply
    button used to be clickable immediately, before either <select> ever
    received real options - clicking it then saved an empty
    backend.model. Must start disabled in markup, not rely solely on JS
    running first."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    apply_button_start = html.index('id="btnConfigApply"')
    apply_button_tag = html[
        html.rindex("<button", 0, apply_button_start) : html.index(
            ">", apply_button_start
        )
    ]
    assert "disabled" in apply_button_tag


def test_app_js_only_enables_apply_once_both_selectors_have_loaded():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    update_fn_start = js.index("function _updateApplyButtonEnabled")
    update_fn_end = js.index("\n}\n", update_fn_start)
    update_body = js[update_fn_start:update_fn_end]
    assert "_modelOptionsLoaded && _microphoneOptionsLoaded" in update_body

    model_fn_start = js.index("function applyModelOptions")
    model_fn_end = js.index("\n}\n", model_fn_start)
    assert "_modelOptionsLoaded = true;" in js[model_fn_start:model_fn_end]

    mic_fn_start = js.index("function applyMicrophoneOptions")
    mic_fn_end = js.index("\n}\n", mic_fn_start)
    assert "_microphoneOptionsLoaded = true;" in js[mic_fn_start:mic_fn_end]


def test_style_css_config_menu_uses_cyan_not_amber_or_red():
    """Saving here is not itself destructive (restart-to-apply only) -
    unlike reset (amber) and shutdown (red), it should not carry warning/
    severity coloring."""
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")

    marker = ".btn-config-toggle {"
    start = css.index(marker)
    rule = css[start : css.index("}", start)]

    assert "var(--cyan)" in rule
    assert "var(--amber)" not in rule
    assert "var(--red)" not in rule


def test_style_css_config_apply_button_looks_visibly_disabled():
    """A technically-disabled button that looks identical to an enabled
    one gives the user no signal for why clicking does nothing."""
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")

    marker = ".btn-config-apply:disabled {"
    start = css.index(marker)
    rule = css[start : css.index("}", start)]

    assert "cursor: not-allowed" in rule


def test_app_js_disables_shutdown_button_immediately_on_confirm():
    """Regression for a real live-session bug (2026-07-07): with no
    engine confirmation to wait for, a confused repeat click on Shutdown
    used to crash pywebview's JS-API dispatch thread once the loop was
    already closed. status_console.py now guards against a closed loop
    (the real fix); disabling the button is the cosmetic layer on top
    that keeps a user from triggering the (now-safe) no-op at all."""
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    start = js.index("function confirmShutdown")
    end = js.index("\n}\n", start)
    body = js[start:end]

    assert 'getElementById("btnShutdown").disabled = true' in body


def test_touchstrip_js_ignores_shutdown_hold_after_first_request():
    js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    start = js.index("function onShutdownHoldStart")
    end = js.index("\n}\n", start)
    body = js[start:end]

    assert "if (_shutdownRequested) return;" in body
    assert "_shutdownRequested = true;" in body


async def test_shutdown_click_before_engine_wiring_is_queued_not_dropped():
    """The window is clickable before run() reaches set_loop()/
    set_shutdown_event(), and the desktop front-end disables its Shutdown
    button on the first click - so a silently dropped early request would
    make UI shutdown permanently unreachable. The request must be
    remembered and dispatched once the wiring completes."""
    bus = EventBus()
    api = StatusConsoleApi(
        thinking_mode=ReasoningLevelState(bus=bus),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
    )

    api.request_shutdown()  # neither loop nor shutdown_event wired yet

    shutdown_event = asyncio.Event()
    api.set_shutdown_event(shutdown_event)
    api.set_loop(asyncio.get_running_loop())

    await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)


def test_status_console_app_uses_ws_transport_instead_of_the_pywebview_api():
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    transport_js = (UI_DIR / "transport.js").read_text(encoding="utf-8")

    assert "new WebSocket" in transport_js
    assert 'channel: "control"' in transport_js
    assert "createTransportStatusHandler" in transport_js
    assert "dispatchStateDelta" in transport_js
    assert "status-console" in app_js
    assert 'default: throw new Error("Unknown state delta' not in app_js
    assert "window.pywebview" not in app_js


def test_mcp_control_waits_for_authoritative_state_instead_of_updating_dom():
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    start = app_js.index("function setMcpEnabled")
    end = app_js.index("\n}", start)
    body = app_js[start:end]

    assert '_sendControl("set_mcp_enabled"' in body
    assert "applyMcpState" not in body


def test_visibility_rendering_does_not_mutate_the_data_source_axis():
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    start = app_js.index("function applyVisibilityMode")
    end = app_js.index("\n}", start)
    body = app_js[start:end]

    assert "dataSource" not in body
    assert "applyDataSource" not in body


# --- story-v1.3.0-task-2: configuration iteration 2 save path ---------------


def _iteration_2_api(bus, ui_config_path):
    return StatusConsoleApi(
        loop=asyncio.get_event_loop(),
        thinking_mode=ReasoningLevelState(bus=EventBus()),
        history=_FakeHistory(),
        bus=bus,
        logger=logger,
        ui_config_path=ui_config_path,
    )


async def test_save_config_selection_writes_iteration_2_sections(tmp_path):
    bus = EventBus()
    ui_config_path = tmp_path / "config.ui.toml"
    api = _iteration_2_api(bus, ui_config_path)

    api.save_config_selection(
        "new-model",
        "USB Headset",
        ui_language="ru",
        vad=VadSettings(threshold=0.7),
        tts_routes={
            "ru": SileroTtsSettings(model="custom_ru", speaker="eugene"),
            "en": PiperTtsSettings(
                model="voices/en.onnx", length_scale=1.2, normalize_audio=False
            ),
        },
    )
    await asyncio.sleep(0.05)

    settings = load_settings(tmp_path / "does-not-exist.toml", ui_path=ui_config_path)
    assert settings.ui.language == "ru"
    assert settings.vad.threshold == 0.7
    assert settings.tts.languages["en"].model == "voices/en.onnx"


async def test_save_config_selection_rejects_out_of_range_vad(tmp_path):
    bus = EventBus()
    system_events: list[SystemEvent] = []
    saved_events: list[UiConfigSaved] = []

    async def on_system_event(event: SystemEvent) -> None:
        system_events.append(event)

    async def on_saved(event: UiConfigSaved) -> None:
        saved_events.append(event)

    bus.subscribe(SystemEvent, on_system_event)
    bus.subscribe(UiConfigSaved, on_saved)
    ui_config_path = tmp_path / "config.ui.toml"
    api = _iteration_2_api(bus, ui_config_path)

    api.save_config_selection(
        "new-model", "USB Headset", vad=VadSettings(threshold=5.0)
    )
    await asyncio.sleep(0.05)

    assert not ui_config_path.exists()
    assert saved_events == []
    assert len(system_events) == 1
    assert system_events[0].level is EventLevel.WARN


async def test_save_config_selection_rejects_partial_tts_routes(tmp_path):
    bus = EventBus()
    ui_config_path = tmp_path / "config.ui.toml"
    api = _iteration_2_api(bus, ui_config_path)

    api.save_config_selection(
        "new-model",
        "USB Headset",
        tts_routes={"ru": SileroTtsSettings()},
    )
    await asyncio.sleep(0.05)

    assert not ui_config_path.exists()
