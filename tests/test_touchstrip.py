import json

import pytest

from status_console import TOUCHSTRIP_HTML, UI_DIR, TouchstripWindow
from ui_contract import EventLevel, RuntimeState, SystemEvent


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


def test_touchstrip_window_uses_touchstrip_html_and_a_fixed_non_resizable_size():
    fake_window = _FakeWindow()
    factory = _fake_factory_returning(fake_window)
    window = TouchstripWindow(window_factory=factory)

    window.create()

    assert factory.kwargs["url"] == str(TOUCHSTRIP_HTML)
    assert factory.kwargs["width"] == 900
    assert factory.kwargs["height"] == 230
    assert factory.kwargs["resizable"] is False


def test_touchstrip_window_reuses_status_console_windows_push_runtime_state():
    fake_window = _FakeWindow()
    window = TouchstripWindow(window_factory=_fake_factory_returning(fake_window))
    window.create()

    window.push_runtime_state(RuntimeState.THINKING)

    assert fake_window.calls[0].startswith("applyRuntimeState(")
    payload = json.loads(fake_window.calls[0][len("applyRuntimeState("):-1])
    assert payload["state"] == "thinking"


def test_touchstrip_window_push_system_event_raises_not_implemented():
    fake_window = _FakeWindow()
    window = TouchstripWindow(window_factory=_fake_factory_returning(fake_window))
    window.create()

    with pytest.raises(NotImplementedError):
        window.push_system_event(
            SystemEvent(timestamp=0.0, source="ENGINE", level=EventLevel.INFO, message="x")
        )


def test_touchstrip_html_has_no_hardcoded_model_name():
    html = TOUCHSTRIP_HTML.read_text(encoding="utf-8")

    assert "gemma" not in html.lower()


def test_touchstrip_html_has_no_google_fonts_or_cdn_reference():
    html = TOUCHSTRIP_HTML.read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_touchstrip_html_uses_open_hidden_labels_not_the_old_ones():
    html = TOUCHSTRIP_HTML.read_text(encoding="utf-8")

    assert "Приватно" not in html
    assert "На людях" not in html


def test_touchstrip_has_no_dense_event_log():
    """Scope: 'No dense event log on touchstrip'."""
    html = TOUCHSTRIP_HTML.read_text(encoding="utf-8")
    js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    assert 'id="logList"' not in html
    assert "appendSystemEvent" not in js


def test_touchstrip_css_has_no_network_loaded_assets():
    css = (UI_DIR / "touchstrip.css").read_text(encoding="utf-8")

    assert "@import" not in css
    assert "http://" not in css
    assert "https://" not in css


def test_touchstrip_js_reuses_the_same_apply_function_names_as_the_desktop_shell():
    """task-ui-06 AC: 'Same state contract as desktop Status Console is
    reused' - both surfaces expose the same apply*() entry points, so
    status_console.py's push_*() methods work unmodified against either."""
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    touchstrip_js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    shared_functions = [
        "function applyRuntimeState(",
        "function applyModuleHealth(",
        "function applyModelLabel(",
        "function applyDataLocality(",
        "function applyThinkingMode(",
        "function applyVisibilityMode(",
    ]
    for function_signature in shared_functions:
        assert function_signature in app_js
        assert function_signature in touchstrip_js


def test_touchstrip_js_has_hold_to_confirm_reset_not_a_tap():
    js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    assert "RESET_HOLD_MS" in js
    assert "setTimeout" in js
    assert "onResetHoldStart" in js
    assert "onResetHoldEnd" in js
    # The reset call must live inside the timeout callback, not fire
    # immediately on pointerdown.
    hold_start = js.index("function onResetHoldStart")
    hold_end = js.index("\n}\n", hold_start)
    assert "reset_context()" in js[hold_start:hold_end]


def test_touchstrip_css_action_buttons_are_large_touch_targets():
    css = (UI_DIR / "touchstrip.css").read_text(encoding="utf-8")

    start = css.index(".act-btn {")
    rule = css[start : css.index("}", start)]
    height_value = rule.split("height:")[1].split(";")[0].strip()
    assert int(height_value.replace("px", "")) >= 100


def test_index_and_demo_and_touchstrip_all_load_the_shared_contract_js():
    index_html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    demo_html = (UI_DIR / "demo.html").read_text(encoding="utf-8")
    touchstrip_html = TOUCHSTRIP_HTML.read_text(encoding="utf-8")

    for html in (index_html, demo_html, touchstrip_html):
        assert 'src="contract.js"' in html


def test_app_js_no_longer_defines_its_own_copy_of_the_contract_consts():
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "const RUNTIME_STATES" not in app_js
    assert "const MODULE_IDS" not in app_js
