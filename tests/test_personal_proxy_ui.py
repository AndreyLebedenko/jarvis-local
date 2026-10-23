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

    assert "proxy_block" not in snapshot
    assert "applyProxyBlock" not in snapshot


def test_the_proxy_status_rides_in_the_snapshot_and_as_a_delta():
    snapshot = APP_JS.split("function _applyStateSnapshot(")[1].split("\n}")[0]
    dispatch_table = APP_JS.split("function _applyStateDelta(")[1].split("\n}")[0]

    assert "applyProxyStatus(state.proxy_status);" in snapshot
    assert "proxy_status: applyProxyStatus," in dispatch_table


def test_the_page_loads_the_proxy_text_before_the_chat_and_the_app_script():
    for page in (INDEX, _read("demo.html")):
        assert page.index('src="proxy_text.js"') < page.index('src="proxy_chat.js"')


def test_the_panel_has_the_dry_run_indicator_and_the_last_block_reason():
    assert 'id="proxyDryRun"' in INDEX
    assert 'id="proxyLastBlock"' in INDEX
    for language in ("en", "ru"):
        keys = _catalog_keys(language)
        assert "proxy_dry_run_indicator" in keys
        assert "proxy_last_block_label" in keys


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


def test_the_dock_works_once_the_session_exists_but_takes_no_attachments():
    sync = APP_JS.split("function _syncJournalInputControls(")[1].split("\n}")[0]

    assert "RUN_MODE.PERSONAL_PROXY" in sync
    assert "proxyMode ||" not in sync
    assert "disabled || proxyMode" in sync
    assert 'classList.toggle("proxy-mode"' in sync
    assert 'id="journalInputProxyNote"' in INDEX
    css = _read("style.css")
    assert ".journal-input-dock.proxy-mode #journalAttachButton" in css
    assert ".journal-input-dock.proxy-mode #journalSendButton" not in css
    assert ".journal-input-dock.proxy-mode.inactive-session" in css


def test_the_dock_note_no_longer_sends_the_user_away_from_the_dock():
    for language in ("en", "ru"):
        body = STRINGS.split(f"  {language}: {{")[1].split("\n  },")[0]
        note = re.search(r"journal_input_proxy_note: \"(.*?)\"", body).group(1)
        assert "first request" in note or "первого запроса" in note
    for language in ("en", "ru"):
        keys = _catalog_keys(language)
        assert "journal_input_proxy_note" in keys
        assert "journal_input_attachments_unavailable" in keys


def test_an_attachment_refusal_is_shown_with_its_own_text():
    body = APP_JS.split("function _journalInputErrorMessage(")[1].split("\n}")[0]

    assert 'payload.reason === "attachments_unavailable"' in body


def test_every_proxy_source_has_a_journal_label_in_both_languages():
    for source in ("proxy_heard", "proxy_sent", "proxy_answer", "proxy_notice"):
        for language in ("en", "ru"):
            assert f"journal_source_{source}" in _catalog_keys(language)


def test_the_contract_mirrors_the_journal_sources_of_the_proxy():
    from jarvis.journal.proxy_exchange import PROXY_HEARD_SOURCE, PROXY_SOURCES

    contract = _read("contract.js")

    assert f'const PROXY_HEARD_SOURCE = "{PROXY_HEARD_SOURCE}";' in contract
    for source in PROXY_SOURCES:
        assert f'"{source}"' in contract.split("PROXY_SOURCES = ")[1].split(";")[0]


def test_a_proxy_label_replaces_the_plain_label_in_the_journal_and_in_search():
    body = APP_JS.split("function _journalExternalAnswerLabel(")[1].split("\n}")[0]

    assert "PROXY_SOURCES.includes(source)" in body
    assert "_journalSourceLabel(source)" in body


def test_a_dock_typed_proxy_request_selects_its_new_session():
    body = APP_JS.split("function _shouldSelectJournalInputSession(")[1].split("\n}")[0]

    assert "PROXY_HEARD_SOURCE" in body


def test_a_proxy_notice_is_drawn_from_its_content_free_record():
    body = APP_JS.split("function _journalEventBodyText(")[1].split("\n}")[0]

    assert 'event.source === "proxy_notice"' in body
    assert "proxyNoticeText(" in body


def _css_rule(selector):
    css = _read("style.css")
    start = css.index(selector + " {")
    return css[start : css.index("}", start)]


def test_the_dock_grid_is_two_columns_when_the_attach_button_is_hidden():
    rule = _css_rule(".journal-input-dock.proxy-mode")

    assert "grid-template-columns: minmax(0, 1fr) auto;" in rule


def test_the_dock_grid_in_normal_mode_keeps_its_three_columns():
    rule = _css_rule(".journal-input-dock")

    assert "grid-template-columns: auto minmax(0, 1fr) auto;" in rule


def test_the_dock_notes_span_every_column_in_both_grids():
    css = _read("style.css")

    for note in ("journal-input-inactive-note", "journal-input-proxy-note"):
        rule = css[css.index(f".{note} {{") :].split("}")[0]
        assert "grid-column: 1 / -1" in rule


def test_nothing_else_is_hidden_by_the_proxy_mode_class_inside_a_layout():
    css = _read("style.css")
    hidden = [
        line
        for line in css.splitlines()
        if "proxy-mode" in line and "display: none" in line
    ]

    assert all("journal-input-dock.proxy-mode" in line for line in hidden)
    assert not re.search(r"\.proxy-chat-input[^{]*proxy-mode", css)
