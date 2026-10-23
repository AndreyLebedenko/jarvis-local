"""Structural checks for the proxy marker and the proxy "New context" in the
Status Console: the page is parsed as text, never run in a browser (the live look
is the human handoff in manual/personal-proxy-session-ux-handoff.md)."""

import re

import pytest

from jarvis.ui.status_console import UI_DIR


def _read(name):
    return (UI_DIR / name).read_text(encoding="utf-8")


APP_JS = _read("app.js")
STRINGS = _read("strings.js")
CSS = _read("style.css")

PROXY_SOURCES = ("proxy_heard", "proxy_sent", "proxy_answer", "proxy_notice")
MARKER_KEYS = (
    "journal_proxy_marker",
    "journal_new_context_ready_proxy",
    "journal_new_context_busy_proxy",
)


def _body(source, header):
    return source.split(header)[1].split("\n}")[0]


def _catalog(language):
    body = STRINGS.split(f"  {language}: {{")[1].split("\n  },")[0]
    return dict(re.findall(r'^    (\w+): "(.*)",?$', body, re.M))


def _rule(selector):
    start = CSS.index("\n" + selector + " {") + 1
    return CSS[start : CSS.index("}", start)]


def _luminance(hex_color):
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground, background):
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _token(name):
    return re.search(rf"^\s*--{name}: (#[0-9A-Fa-f]{{6}});", CSS, re.M).group(1)


# --- the marker ---------------------------------------------------------------


def test_the_marker_icon_is_part_of_the_one_icon_set():
    assert "proxy_out: " in APP_JS.split("const ICON_PATHS = {")[1].split("\n};")[0]


def test_the_marker_is_an_icon_with_an_accessible_name_and_a_title():
    body = _body(APP_JS, "function _proxyMarkerElement(")

    assert 'className = "proxy-marker"' in body
    assert 'setAttribute("role", "img")' in body
    assert 'uiString("journal_proxy_marker")' in body
    assert "marker.title" in body
    assert 'setAttribute("aria-label"' in body
    assert '_icon("proxy_out")' in body


def test_a_proxy_session_row_gets_the_class_and_the_icon_and_no_other_row_does():
    body = _body(APP_JS, "function _journalSessionElement(")

    assert 'session.title_kind === "proxy_session"' in body
    assert 'row.classList.toggle("proxy-marked", isProxy)' in body
    assert "_proxyMarkerElement()" in body
    assert body.index("isProxy") < body.index("_proxyMarkerElement()")


def test_every_proxy_message_kind_gets_the_class_and_the_icon_in_its_header():
    body = _body(APP_JS, "function _journalEventElement(")

    assert "PROXY_SOURCES.includes(event.source)" in body
    assert 'message.classList.add("proxy-marked")' in body
    assert "meta.prepend(_proxyMarkerElement())" in body


def test_the_message_sources_the_marker_follows_are_the_four_proxy_sources():
    contract = _read("contract.js")

    listed = contract.split("PROXY_SOURCES = ")[1].split(";")[0]
    assert tuple(re.findall(r'"(\w+)"', listed)) == PROXY_SOURCES


def test_the_marker_never_changes_the_session_title_text():
    body = _body(APP_JS, "function _journalSessionElement(")

    assert "title.textContent = _journalSessionTitle(session);" in body


@pytest.mark.parametrize("language", ["en", "ru"])
def test_the_marker_and_the_new_session_strings_exist_with_text(language):
    catalog = _catalog(language)

    for key in MARKER_KEYS:
        assert catalog.get(key), (language, key)


def test_the_marker_icon_is_not_an_external_asset_or_an_emoji():
    paths = APP_JS.split("proxy_out: ")[1].split("\n  ", 1)[0]

    assert "http" not in paths
    assert all(ord(character) < 128 for character in paths)


# --- the amber accent -----------------------------------------------------------


@pytest.mark.parametrize("token", ["amber", "amber-dim", "amber-tint"])
def test_the_amber_tokens_the_accent_uses_exist_in_the_palette(token):
    assert re.search(rf"^\s*--{token}:", CSS.split("}")[0], re.M)


def test_the_theme_is_a_single_dark_one_so_the_marker_has_one_palette():
    assert "prefers-color-scheme" not in CSS
    assert "data-theme" not in CSS


def test_a_marked_session_row_has_an_amber_edge_and_nothing_else_changes():
    rule = _rule(".journal-session.proxy-marked")

    assert "border-left: 3px solid var(--amber);" in rule
    assert "background" not in rule
    assert "border-color" not in rule


def test_a_marked_message_has_an_amber_edge_and_keeps_its_role_fill():
    rule = _rule(".journal-msg.proxy-marked")

    assert "border-left: 3px solid var(--amber);" in rule
    assert "background" not in rule


def test_the_marker_icon_is_amber_and_has_a_size_that_reads_small():
    rule = _rule(".proxy-marker")

    assert "color: var(--amber);" in rule
    sized = _rule(".proxy-marker .icon")
    assert re.search(r"width: (1[4-9]|2\d)px;", sized)


def test_the_marked_rules_come_after_the_selection_rule_so_the_edge_wins():
    assert CSS.index(".journal-session.proxy-marked {") > CSS.index(
        ".journal-session.sel {"
    )


def test_no_marker_rule_hardcodes_a_color():
    for selector in (
        ".journal-session.proxy-marked",
        ".journal-msg.proxy-marked",
        ".proxy-marker",
        ".proxy-marker .icon",
    ):
        assert not re.search(r"#[0-9A-Fa-f]{3,6}\b|rgb", _rule(selector)), selector


@pytest.mark.parametrize("surface", ["bg", "panel", "panel-2"])
def test_the_amber_icon_reads_against_every_surface_it_sits_on(surface):
    assert _contrast(_token("amber"), _token(surface)) >= 4.5


# --- the button in the proxy mode ----------------------------------------------


def test_the_run_mode_check_is_shared_by_the_dock_and_the_new_context():
    helper = _body(APP_JS, "function _isProxyRunMode(")

    assert "RUN_MODE.PERSONAL_PROXY" in helper
    sync = _body(APP_JS, "function _syncJournalInputControls(")
    assert "_isProxyRunMode()" in sync


def test_a_busy_refusal_in_the_proxy_mode_says_a_request_or_a_question_is_waiting():
    body = _body(APP_JS, "function _journalNewContextErrorMessage(")

    assert 'payload.reason === "busy"' in body
    assert "_isProxyRunMode()" in body
    assert '"journal_new_context_busy_proxy"' in body
    assert '"journal_new_context_busy"' in body


def test_a_ready_session_in_the_proxy_mode_says_the_next_request_starts_it():
    body = _body(APP_JS, "async function startNewJournalContext(")

    assert 'uiString("journal_new_context_ready_proxy")' in body
    assert 'uiString("journal_new_context_ready")' in body


def test_a_proxy_session_without_an_id_leaves_nothing_selected_and_the_dock_inactive():
    body = _body(APP_JS, "async function startNewJournalContext(")

    assert "_journalSelectedSessionId = payload.session_id || null;" in body
    assert "_journalActiveSessionId = payload.session_id || null;" in body
    assert "if (payload.session_id) selectJournalSession(payload.session_id);" in body


def test_the_dock_stays_inactive_with_the_dry_run_aware_note_until_the_session_exists():
    sync = _body(APP_JS, "function _syncJournalInputControls(")
    status = _body(_read("proxy_chat.js"), "function applyProxyStatus(")

    assert "_journalInputTargetsSelectedSession()" in sync
    assert "journal_input_proxy_note_dry_run" in status
    assert "journal_input_proxy_note" in status


def test_an_accepted_new_context_in_the_proxy_clears_only_the_chat_blocks():
    body = _body(APP_JS, "async function startNewJournalContext(")
    accepted = body.split('payload.status === "ok"')[1].split("return;")[0]

    assert "if (_isProxyRunMode()) clearProxyChatBlocks();" in accepted
    refused = body.split("return;\n    }")[1]
    assert "clearProxyChatBlocks" not in refused


def test_the_proxy_chat_clears_blocks_separately_from_input_and_status():
    chat = _read("proxy_chat.js")
    blocks = _body(chat, "function clearProxyChatBlocks(")

    assert "proxyChatText" not in blocks
    assert "_setProxyChatStatus" not in blocks
    assert "clearProxyChatBlocks();" in _body(chat, "function clearProxyChat(")


def test_the_proxy_mode_skips_the_leave_confirmation_but_keeps_the_memory_one():
    body = _body(APP_JS, "function _confirmStartNewJournalContext(")

    assert "_confirmDiscardJournalMemoryChanges()" in body
    assert body.index("_confirmDiscardJournalMemoryChanges()") < body.index(
        "_isProxyRunMode()"
    )
    assert "if (_isProxyRunMode()) return true;" in body


def test_an_unavailable_proxy_gets_its_own_text_not_the_busy_one():
    body = _body(APP_JS, "function _journalNewContextErrorMessage(")

    assert body.index('payload.reason === "unavailable"') < body.index(
        'payload.reason === "busy"'
    )
    assert '"journal_new_context_unavailable"' in body
    for language in ("en", "ru"):
        assert _catalog(language).get("journal_new_context_unavailable")


def test_the_ready_text_in_the_proxy_says_how_to_start_the_request():
    ready = "journal_new_context_ready_proxy"

    assert "type it in the Personal proxy panel" in _catalog("en")[ready]
    assert "панели" in _catalog("ru")[ready]
