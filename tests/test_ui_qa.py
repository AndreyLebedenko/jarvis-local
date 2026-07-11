"""task-ui-07: consolidated visual/manual QA checks.

Each individual task-ui-02..06 card already asserted its own slice (e.g.
"index.html has no CDN reference"). This file adds the checks that only
make sense once every surface exists together: scanning the *whole*
status_console_ui/ directory at once (so a new file can't slip past the
per-file checks by never getting one written for it), and confirming all
six RuntimeStates map to a distinct color on *both* surfaces, not just
the three (warming/error/speaking) task-ui-02 originally distinguished.
"""

from pathlib import Path
import re

import pytest

from jarvis.ui.status_console import UI_DIR
from jarvis.ui.contract import RuntimeState

_NETWORK_MARKERS = ("http://", "https://", "fonts.googleapis.com")
_RUNTIME_COLOR_PROPERTIES = ("--live", "--live-dim", "--live-tint")


def _all_ui_source_files() -> list[Path]:
    return (
        sorted(UI_DIR.glob("*.html"))
        + sorted(UI_DIR.glob("*.css"))
        + sorted(UI_DIR.glob("*.js"))
    )


def test_every_status_console_ui_file_is_covered_by_the_network_asset_scan():
    """Guards against a new file being added to status_console_ui/ without
    anyone ever writing a "no CDN" test for it specifically."""
    found = {path.name for path in _all_ui_source_files()}
    expected = {
        "app.js",
        "contract.js",
        "demo.html",
        "demo.js",
        "index.html",
        "strings.js",
        "style.css",
        "touchstrip.css",
        "touchstrip.html",
        "touchstrip.js",
        "transport.js",
    }
    assert found == expected


@pytest.mark.parametrize("path", _all_ui_source_files(), ids=lambda p: p.name)
def test_no_status_console_ui_file_references_a_network_asset(path):
    text = path.read_text(encoding="utf-8")
    for marker in _NETWORK_MARKERS:
        assert marker not in text, f"{path.name} contains {marker!r}"


def _root_custom_properties(css_text: str) -> dict[str, str]:
    root_start = css_text.index(":root")
    root_body_start = css_text.index("{", root_start) + 1
    root_body_end = css_text.index("}", root_body_start)
    root_body = css_text[root_body_start:root_body_end]
    return {
        match.group("name"): match.group("value").strip()
        for match in re.finditer(
            r"(?P<name>--[a-z0-9-]+)\s*:\s*(?P<value>[^;]+);",
            root_body,
        )
    }


def _resolve_css_value(value: str, custom_properties: dict[str, str]) -> str:
    var_match = re.fullmatch(r"var\((--[a-z0-9-]+)\)", value)
    if var_match is None:
        return value
    token = var_match.group(1)
    assert token in custom_properties
    return custom_properties[token]


def _runtime_color_rules(css_text: str) -> dict[str, dict[str, str]]:
    custom_properties = _root_custom_properties(css_text)
    colors = {}
    for state in RuntimeState:
        marker = f'html[data-state="{state.value}"]'
        start = css_text.index(marker)
        rule = css_text[start : css_text.index("}", start)]
        state_colors = {}
        for property_name in _RUNTIME_COLOR_PROPERTIES:
            color_start = rule.index(f"{property_name}:") + len(property_name) + 1
            raw_value = rule[color_start : rule.index(";", color_start)].strip()
            state_colors[property_name] = _resolve_css_value(
                raw_value, custom_properties
            )
        colors[state.value] = state_colors
    return colors


def test_style_css_gives_every_runtime_state_a_rule():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    colors = _runtime_color_rules(css)

    assert set(colors) == {state.value for state in RuntimeState}


def test_touchstrip_css_gives_every_runtime_state_a_rule():
    css = (UI_DIR / "touchstrip.css").read_text(encoding="utf-8")
    colors = _runtime_color_rules(css)

    assert set(colors) == {state.value for state in RuntimeState}


def test_style_css_and_touchstrip_css_agree_on_every_runtime_state_color():
    """The two surfaces should read as the same product, not two
    independently-tuned palettes that could drift apart color by color.
    Compare resolved custom-property values, not just matching var(...)
    references, so changing --amber-warm in only one CSS file fails here."""
    desktop_colors = _runtime_color_rules(
        (UI_DIR / "style.css").read_text(encoding="utf-8")
    )
    touchstrip_colors = _runtime_color_rules(
        (UI_DIR / "touchstrip.css").read_text(encoding="utf-8")
    )

    assert desktop_colors == touchstrip_colors


def test_demo_html_respects_style_css_narrow_width_breakpoint():
    """Regression for a real bug found live during task-ui-07's consolidated
    QA pass: demo.html's inline <style> block unconditionally set
    body{grid-template-areas} to the wide "main log" two-column layout,
    which won the cascade over style.css's own @media (max-width: 720px)
    override (same selector specificity, declared later in the document -
    the inline <style> tag comes after style.css's <link>). demo.html never
    actually exercised the responsive stacked layout at narrow widths,
    silently squeezing .main to ~83px wide instead of stacking full-width -
    caught by measuring live layout via the Preview tools, not by the
    existing "no horizontal overflow" checks alone, which this bug did not
    trip."""
    demo_html = (UI_DIR / "demo.html").read_text(encoding="utf-8")

    assert "@media (max-width: 720px)" in demo_html
    media_query_body = demo_html[demo_html.index("@media (max-width: 720px)") :]
    assert '"main" "log"' in media_query_body
