import json

import pytest

from status_console import (
    INDEX_HTML,
    UI_DIR,
    StatusConsoleWindow,
    data_locality_payload,
    module_health_payload,
    runtime_state_payload,
    system_event_payload,
)
from ui_contract import (
    DataLocality,
    EventLevel,
    HealthStatus,
    ModuleHealth,
    ModuleId,
    RuntimeState,
    SystemEvent,
)


@pytest.mark.parametrize("state", list(RuntimeState))
def test_runtime_state_payload_covers_every_contract_state(state):
    payload = runtime_state_payload(state)

    assert payload["state"] == state.value
    assert payload["label"]  # every state has a non-empty label
    assert "substatus" in payload


def test_runtime_state_payload_uses_given_substatus_over_the_default():
    payload = runtime_state_payload(RuntimeState.ERROR, substatus="TTS: device not found")

    assert payload["substatus"] == "TTS: device not found"


def test_module_health_payload_shape():
    health = ModuleHealth(module=ModuleId.TTS, status=HealthStatus.DEGRADED, detail="slow")

    assert module_health_payload(health) == {
        "module": "tts",
        "status": "degraded",
        "detail": "slow",
    }


def test_data_locality_payload_shape():
    assert data_locality_payload(DataLocality.EXTERNAL) == {"locality": "external"}


class _FakeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def evaluate_js(self, script: str) -> None:
        self.calls.append(script)


def _fake_factory_returning(fake_window):
    def factory(**kwargs):
        factory.kwargs = kwargs
        return fake_window

    return factory


def test_create_passes_index_html_url_and_no_hardcoded_model_name():
    fake_window = _FakeWindow()
    factory = _fake_factory_returning(fake_window)
    console = StatusConsoleWindow(window_factory=factory)

    console.create()

    assert factory.kwargs["url"] == str(INDEX_HTML)
    assert "gemma" not in json.dumps(factory.kwargs).lower()


def test_push_runtime_state_evaluates_js_with_contract_payload():
    fake_window = _FakeWindow()
    console = StatusConsoleWindow(window_factory=_fake_factory_returning(fake_window))
    console.create()

    console.push_runtime_state(RuntimeState.WARMING)

    assert len(fake_window.calls) == 1
    assert fake_window.calls[0].startswith("applyRuntimeState(")
    payload = json.loads(fake_window.calls[0][len("applyRuntimeState("):-1])
    assert payload["state"] == "warming"


def test_push_module_health_evaluates_js_with_contract_payload():
    fake_window = _FakeWindow()
    console = StatusConsoleWindow(window_factory=_fake_factory_returning(fake_window))
    console.create()

    console.push_module_health(ModuleHealth(module=ModuleId.VISION, status=HealthStatus.OK))

    payload = json.loads(fake_window.calls[0][len("applyModuleHealth("):-1])
    assert payload == {"module": "vision", "status": "ok", "detail": ""}


def test_push_data_locality_evaluates_js_with_contract_payload():
    fake_window = _FakeWindow()
    console = StatusConsoleWindow(window_factory=_fake_factory_returning(fake_window))
    console.create()

    console.push_data_locality(DataLocality.LOCAL)

    payload = json.loads(fake_window.calls[0][len("applyDataLocality("):-1])
    assert payload == {"locality": "local"}


def test_push_model_label_evaluates_js_with_given_label():
    fake_window = _FakeWindow()
    console = StatusConsoleWindow(window_factory=_fake_factory_returning(fake_window))
    console.create()

    console.push_model_label("gemma4:12b-it-qat")

    payload = json.loads(fake_window.calls[0][len("applyModelLabel("):-1])
    assert payload == {"label": "gemma4:12b-it-qat"}


def test_system_event_payload_shape():
    event = SystemEvent(
        timestamp=1234.5, source="WARMUP", level=EventLevel.WARN, message="слишком долго"
    )

    assert system_event_payload(event) == {
        "timestamp": 1234.5,
        "source": "WARMUP",
        "level": "warn",
        "message": "слишком долго",
        "correlation_id": None,
    }


def test_push_system_event_evaluates_js_with_contract_payload():
    fake_window = _FakeWindow()
    console = StatusConsoleWindow(window_factory=_fake_factory_returning(fake_window))
    console.create()

    console.push_system_event(
        SystemEvent(timestamp=1.0, source="ENGINE", level=EventLevel.INFO, message="ready")
    )

    assert fake_window.calls[0].startswith("appendSystemEvent(")
    payload = json.loads(fake_window.calls[0][len("appendSystemEvent("):-1])
    assert payload["source"] == "ENGINE"
    assert payload["level"] == "info"


def test_pushing_state_before_create_raises():
    console = StatusConsoleWindow(window_factory=_fake_factory_returning(_FakeWindow()))

    with pytest.raises(RuntimeError):
        console.push_runtime_state(RuntimeState.IDLE)


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

    assert "meta.textContent = payload.detail || \"\";" in js
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
