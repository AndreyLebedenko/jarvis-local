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


def _catalog_text(language):
    body = STRINGS.split(f"  {language}: {{")[1].split("\n  },")[0]
    return dict(re.findall(r'^    (\w+): "(.*)",?$', body, re.M))


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
    assert "clearProxyChatBlocks();" in body


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


def test_the_status_panel_has_no_input_and_no_way_to_submit_text():
    panel = INDEX.split('id="proxyChat"')[1].split("</section>")[0]

    for forbidden in ("<textarea", "<form", "<input", "<button", "proxyChatText"):
        assert forbidden not in panel
    for removed in ("submitProxyText", "onProxyChatKeyDown", "proxyChatText"):
        assert removed not in PROXY_JS
        assert removed not in APP_JS
        assert removed not in INDEX


def test_the_dock_posts_typed_requests_to_the_route_the_engine_reroutes():
    body = APP_JS.split("async function submitJournalInput(")[1].split("\n}")[0]

    assert '_journalUrl("/api/journal/input")' in body


def test_the_status_panel_hint_points_to_speech_or_the_journal_dock():
    for language, words in (
        ("en", ("Speak", "Journal dock")),
        ("ru", ("Скажите", "Журнал")),
    ):
        hint = _catalog_text(language)["proxy_chat_empty"]
        assert all(word in hint for word in words), (language, hint)
        assert "below" not in hint and "ниже" not in hint


def test_no_string_still_sends_the_user_to_the_removed_status_input():
    for language in ("en", "ru"):
        for key, text in _catalog_text(language).items():
            assert "Personal proxy panel" not in text, (language, key)
            assert "панели «Личный прокси»" not in text, (language, key)
            assert not key.startswith("proxy_chat_") or key in (
                "proxy_chat_title",
                "proxy_chat_empty",
            ), (language, key)


def test_the_dock_takes_requests_in_the_proxy_but_no_attachments():
    sync = APP_JS.split("function _syncJournalInputControls(")[1].split("\n}")[0]

    helper = APP_JS.split("function _isProxyRunMode(")[1].split("\n}")[0]
    assert "RUN_MODE.PERSONAL_PROXY" in helper
    assert "_isProxyRunMode()" in sync
    assert "proxyMode ||" not in sync
    assert "disabled || proxyMode" in sync
    assert 'classList.toggle("proxy-mode"' in sync
    assert 'id="journalInputProxyNote"' in INDEX
    css = _read("style.css")
    assert ".journal-input-dock.proxy-mode #journalAttachButton" in css
    assert ".journal-input-dock.proxy-mode #journalSendButton" not in css
    assert ".journal-input-dock.proxy-mode.inactive-session" in css


def test_the_dock_note_explains_an_older_session_and_says_how_to_type():
    for language, words in (
        ("en", ("older session", "live session", "new context")),
        ("ru", ("прежняя сессия", "текущую сессию", "новый контекст")),
    ):
        note = _catalog_text(language)["journal_input_proxy_note"]
        assert all(word in note for word in words), (language, note)
    for language in ("en", "ru"):
        keys = _catalog_keys(language)
        assert "journal_input_proxy_note" in keys
        assert "journal_input_proxy_note_dry_run" not in keys
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


def test_the_dry_run_status_and_new_session_texts_exist_in_both_languages():
    for language in ("en", "ru"):
        text = _catalog_text(language)
        assert text["journal_input_sent_dry_run"]
        assert text["journal_proxy_new_session_empty"]
        assert text["proxy_sent_default_system"]
    assert "Status" in _catalog_text("en")["journal_input_sent_dry_run"]
    assert "Статус" in _catalog_text("ru")["journal_input_sent_dry_run"]


def test_every_string_the_dock_and_feed_use_for_the_proxy_exists_in_both_languages():
    used = set(
        re.findall(
            r'"(journal_proxy_new_session_empty|journal_input_sent_dry_run|proxy_sent_default_system)"',
            APP_JS + PROXY_JS,
        )
    )

    assert used == {
        "journal_proxy_new_session_empty",
        "journal_input_sent_dry_run",
        "proxy_sent_default_system",
    }
    for language in ("en", "ru"):
        assert used <= _catalog_keys(language)


def test_the_folded_system_prompt_has_a_visible_label_style():
    css = _read("style.css")

    assert ".proxy-system-default-label" in css
    assert (
        "cursor: pointer" in css.split(".proxy-system-default-label")[1].split("}")[0]
    )


def test_the_dock_has_a_note_that_a_request_starts_a_new_session():
    assert 'id="journalInputNewSessionNote"' in INDEX
    sync = APP_JS.split("function _syncJournalInputControls(")[1].split("\n}")[0]
    assert '"starts-new-session"' in sync
    for language in ("en", "ru"):
        assert _catalog_text(language)["journal_input_proxy_new_session_note"]
    rule = _read("style.css").split(".journal-input-new-session-note {")[1]
    assert "grid-column: 1 / -1" in rule.split("}")[0]
    assert ".journal-input-dock.starts-new-session .journal-input-new-session-note" in (
        _read("style.css")
    )
