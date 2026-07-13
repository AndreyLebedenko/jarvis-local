from jarvis.ui.status_console import TOUCHSTRIP_HTML, UI_DIR, TouchstripWindow


class _FakeWindow:
    def destroy(self) -> None:
        pass

    def load_url(self, url: str) -> None:
        self.loaded_url = url


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


def test_touchstrip_window_is_only_a_transport_served_window_shell():
    fake_window = _FakeWindow()
    factory = _fake_factory_returning(fake_window)
    window = TouchstripWindow(window_factory=factory)
    window.create(url="http://127.0.0.1:1234/touchstrip.html?token=t")

    assert factory.kwargs["url"].endswith("/touchstrip.html?token=t")
    assert not hasattr(window, "push_runtime_state")


def test_touchstrip_window_navigates_to_the_transport_after_creation():
    fake_window = _FakeWindow()
    window = TouchstripWindow(window_factory=_fake_factory_returning(fake_window))
    window.create()

    window.load_url("http://127.0.0.1:1234/touchstrip.html?token=t")

    assert fake_window.loaded_url.endswith("/touchstrip.html?token=t")


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
    reused' - both surfaces expose the same apply*() entry points for the
    shared WebSocket state projection."""
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
    assert 'sendUiControl("reset_context")' in js[hold_start:hold_end]


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
    assert 'src="transport.js"' in index_html
    assert 'src="transport.js"' in touchstrip_html


def test_app_js_no_longer_defines_its_own_copy_of_the_contract_consts():
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "const RUNTIME_STATES" not in app_js
    assert "const MODULE_IDS" not in app_js
    assert "const REASONING_LEVELS" not in app_js


def test_surfaces_delegate_unknown_delta_handling_to_shared_transport_glue():
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    touchstrip_js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    assert "dispatchStateDelta(payload" in app_js
    assert "dispatchStateDelta(payload" in touchstrip_js


# --- story-v1.3.1 task 4: graded reasoning-level UI -------------------------


def test_apply_thinking_mode_never_infers_the_level_from_is_enabled():
    """Stop condition: 'the UI has to infer a level from is_enabled' -
    both surfaces must read payload.level directly."""
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    touchstrip_js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    for js in (app_js, touchstrip_js):
        start = js.index("function applyThinkingMode(")
        end = js.index("\n}\n", start)
        body = js[start:end]
        assert "payload.level" in body
        assert "is_enabled" not in body


def test_touchstrip_thinking_button_still_sends_the_compatibility_cycle_command():
    """task 4 item 4: touchstrip stays one compact Thinking action that
    cycles, unlike the desktop's direct four-way selection."""
    html = TOUCHSTRIP_HTML.read_text(encoding="utf-8")
    js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    assert 'onclick="toggleThinking()"' in html
    assert "function toggleThinking()" in js
    assert 'sendUiControl("toggle_thinking")' in js


def test_touchstrip_displays_the_exact_reasoning_level_value():
    js = (UI_DIR / "touchstrip.js").read_text(encoding="utf-8")

    assert "REASONING_LEVELS.includes(payload.level)" in js
    assert '"level: " + payload.level' in js


def test_demo_can_render_all_four_reasoning_levels_without_a_live_backend():
    demo_html = (UI_DIR / "demo.html").read_text(encoding="utf-8")
    demo_js = (UI_DIR / "demo.js").read_text(encoding="utf-8")

    assert 'id="reasoningLevelToggle"' in demo_html
    for level in ("off", "low", "medium", "high"):
        assert f'data-level="{level}"' in demo_html
    assert "for (const level of REASONING_LEVELS)" in demo_js
    assert "applyThinkingMode({ level })" in demo_js

    # Same stop condition as index.html: no button preselected in markup.
    toggle_start = demo_html.index('id="reasoningLevelToggle"')
    toggle_end = demo_html.index("</div>", toggle_start)
    assert "sel" not in demo_html[toggle_start:toggle_end]
