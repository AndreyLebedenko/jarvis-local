"""Structural checks for the personal proxy's part of the Status Console: the
page is parsed as text, never run in a browser (the live look is the human
handoff)."""

import re

import pytest

from jarvis.core.run_mode import RunMode
from jarvis.ui.status_console import UI_DIR


def _read(name):
    return (UI_DIR / name).read_text(encoding="utf-8")


APP_JS = _read("app.js")
PROXY_JS = _read("proxy_chat.js")
INDEX = _read("index.html")
STRINGS = _read("strings.js")


def _catalog_keys(language):
    body = STRINGS.split(f"  {language}: {{")[1].split("\n  },")[0]
    return set(re.findall(r"^    (\w+):", body, re.M))


def test_the_page_loads_the_proxy_chat_before_the_app_script():
    assert INDEX.index('src="proxy_chat.js"') < INDEX.index('src="app.js"')
    assert 'src="proxy_chat.js"' in _read("demo.html")


def test_a_proxy_block_delta_is_dispatched_to_the_chat():
    dispatch_table = APP_JS.split("function _applyStateDelta(")[1].split("\n}")[0]

    assert "proxy_block: applyProxyBlock," in dispatch_table


def test_the_proxy_block_is_never_part_of_the_snapshot_handling():
    snapshot = APP_JS.split("function _applyStateSnapshot(")[1].split("\n}")[0]

    assert "proxy" not in snapshot


def test_every_proxy_string_the_chat_uses_exists_in_both_languages():
    used = set(re.findall(r'"(proxy_\w+)"', PROXY_JS))

    assert used
    assert used <= _catalog_keys("en")
    assert used <= _catalog_keys("ru")


@pytest.mark.parametrize("mode", [RunMode.MCP, RunMode.PERSONAL_PROXY])
def test_each_badge_mode_has_a_label_and_a_hint_in_both_languages(mode):
    for language in ("en", "ru"):
        keys = _catalog_keys(language)
        assert f"run_mode_{mode.value}_label" in keys
        assert f"run_mode_{mode.value}_hint" in keys


def test_the_contract_names_the_personal_proxy_run_mode():
    assert 'PERSONAL_PROXY: "personal_proxy"' in _read("contract.js")
    assert RunMode.PERSONAL_PROXY.value == "personal_proxy"


def test_the_chat_never_puts_text_in_as_markup_or_keeps_it():
    for forbidden in (
        "innerHTML",
        "insertAdjacentHTML",
        "localStorage",
        "sessionStorage",
    ):
        assert forbidden not in PROXY_JS
    assert "document.cookie" not in PROXY_JS


def test_the_chat_is_wiped_when_the_window_goes_hidden():
    assert (
        "_onProxyVisibilityChanged(payload.mode);"
        in APP_JS.split("function applyVisibilityMode(")[1].split("\n}")[0]
    )
    body = PROXY_JS.split("function _onProxyVisibilityChanged(")[1].split("\n}")[0]
    assert 'mode === "hidden"' in body
    assert "clearProxyChat();" in body


def test_a_block_is_ignored_while_hidden():
    body = PROXY_JS.split("function applyProxyBlock(")[1].split("\n}")[0]

    assert "if (_isHiddenActive()) return;" in body


def test_the_chat_panel_is_shown_only_in_the_personal_proxy_run_mode():
    css = _read("style.css")

    assert ".proxy-chat { display: none;" in css
    assert 'html[data-run-mode="personal_proxy"] .proxy-chat { display: block; }' in css
    assert 'id="proxyChat"' in INDEX


def test_a_sentence_made_by_plain_substitution_is_marked_rough():
    body = PROXY_JS.split("function _proxyAnswerSentence(")[1].split("\n}")[0]

    assert 'payload.method === "substituted"' in body
    assert "payload.unresolved === true" in body


def test_typed_text_goes_to_the_dock_route_that_the_engine_reroutes():
    body = PROXY_JS.split("async function submitProxyText(")[1].split("\n}")[0]

    assert '_journalUrl("/api/journal/input")' in body


def test_the_dock_points_to_the_proxy_panel_and_cannot_send_in_this_mode():
    sync = APP_JS.split("function _syncJournalInputControls(")[1].split("\n}")[0]

    assert "RUN_MODE.PERSONAL_PROXY" in sync
    assert "proxyMode ||" in sync
    assert 'classList.toggle("proxy-mode"' in sync
    assert 'id="journalInputProxyNote"' in INDEX
    css = _read("style.css")
    assert ".journal-input-dock.proxy-mode #journalSendButton" in css
    for language in ("en", "ru"):
        keys = _catalog_keys(language)
        assert "journal_input_proxy_note" in keys
        assert "journal_input_attachments_unavailable" in keys


def test_an_attachment_refusal_is_shown_with_its_own_text():
    body = APP_JS.split("function _journalInputErrorMessage(")[1].split("\n}")[0]

    assert 'payload.reason === "attachments_unavailable"' in body
