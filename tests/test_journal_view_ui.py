"""task-journal-05: structural checks for the static Journal view.

Same approach as tests/test_ui_qa.py: parse the UI sources as text/HTML
and assert structure, never run a browser (Testing protocol - the visual
pass is a human-run handoff).
"""

import re
from html.parser import HTMLParser

from jarvis.ui.status_console import UI_DIR

INDEX_HTML = (UI_DIR / "index.html").read_text(encoding="utf-8")
STYLE_CSS = (UI_DIR / "style.css").read_text(encoding="utf-8")
APP_JS = (UI_DIR / "app.js").read_text(encoding="utf-8")
STRINGS_JS = (UI_DIR / "strings.js").read_text(encoding="utf-8")

JOURNAL_STRING_KEYS = (
    "view_console",
    "view_journal",
    "journal_sessions_title",
    "journal_no_sessions",
    "journal_no_selection",
    "journal_empty_feed",
    "journal_hidden_placeholder",
    "journal_source_voice",
    "journal_source_text",
    "journal_source_dock",
    "journal_source_assistant",
    "journal_source_fork",
    "journal_source_context",
    "journal_search_label",
    "journal_search_placeholder",
    "journal_search_date_from",
    "journal_search_date_to",
    "journal_search_clear",
    "journal_search_no_results",
    "journal_input_placeholder",
    "journal_input_send",
    "journal_input_busy",
    "journal_input_hidden",
    "journal_input_empty",
    "journal_input_over_limit",
    "journal_input_failed",
    "journal_input_sent",
    "journal_copy_answer",
    "journal_copy_done",
    "journal_copy_failed",
    "journal_image_missing",
    "journal_usage_total",
    "journal_new_context",
    "journal_new_context_confirm",
    "journal_new_context_ready",
    "journal_new_context_required",
    "journal_new_context_busy",
    "journal_new_context_hidden",
    "journal_new_context_failed",
    "journal_memory_open",
    "journal_memory_close",
    "journal_memory_title",
    "journal_memory_note",
    "journal_memory_self_title",
    "journal_memory_self_description",
    "journal_memory_memory_title",
    "journal_memory_memory_description",
    "journal_memory_save",
    "journal_memory_saved",
    "journal_memory_counter",
    "journal_memory_over_limit",
    "journal_memory_hidden",
    "journal_memory_load_failed",
    "journal_memory_save_failed",
    "journal_memory_discard_confirm",
    "journal_session_delete",
    "journal_session_continue",
    "journal_session_active",
    "journal_delete_confirm",
    "journal_delete_failed",
    "journal_delete_active",
    "journal_delete_not_found",
    "journal_fork_started",
    "journal_fork_busy",
    "journal_fork_hidden",
    "journal_fork_unknown",
    "journal_fork_oversize",
    "journal_fork_failed",
    "journal_fork_truncated",
)


class _JournalViewParser(HTMLParser):
    """Collects the element tree and text nodes of #journalView."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.texts = []  # (text, owning tag attrs) for text inside the view
        self.input_dock_depth = None
        self.input_dock_tags = []
        self.view_toggle_buttons = []
        self._attr_stack = []
        self._in_view_toggle_depth = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if attrs_dict.get("id") == "journalView":
            self.depth = 1
            self._attr_stack = [attrs_dict]
            return
        if self.depth:
            self.depth += 1
            self._attr_stack.append(attrs_dict)
            if attrs_dict.get("id") == "journalInputDock":
                self.input_dock_depth = self.depth
            if self.input_dock_depth:
                self.input_dock_tags.append((tag, attrs_dict))
        if attrs_dict.get("id") == "viewToggle":
            self._in_view_toggle_depth = 1
        elif self._in_view_toggle_depth:
            self._in_view_toggle_depth += 1
            if tag == "button":
                self.view_toggle_buttons.append(attrs_dict)

    def handle_endtag(self, tag):
        if self.depth:
            if self.depth == self.input_dock_depth:
                self.input_dock_depth = None
            self.depth -= 1
            self._attr_stack.pop()
        if self._in_view_toggle_depth:
            self._in_view_toggle_depth -= 1

    def handle_data(self, data):
        if self.depth and data.strip():
            self.texts.append((data.strip(), self._attr_stack[-1]))


def _parse_journal_view():
    parser = _JournalViewParser()
    parser.feed(INDEX_HTML)
    return parser


def test_header_has_console_journal_switcher():
    parser = _parse_journal_view()
    views = [button.get("data-view") for button in parser.view_toggle_buttons]
    assert views == ["console", "journal"]
    for button in parser.view_toggle_buttons:
        assert "setActiveView(" in button.get("onclick", "")
        assert button.get("data-i18n") in ("view_console", "view_journal")


def test_switcher_toggles_view_visibility_via_css():
    """The journal replaces the central column and is invisible by default
    (data-view="console" on <html> keeps the Console view untouched)."""
    assert 'data-view="console"' in INDEX_HTML.split("<body>")[0]
    compact = re.sub(r"\s+", " ", STYLE_CSS)
    assert ".journal { display: none; }" in compact
    assert 'html[data-view="journal"] .main { display: none; }' in compact
    assert re.search(
        r'html\[data-view="journal"\] \.journal \{[^}]*display: grid;', compact
    )


def test_system_events_panel_is_hidden_in_journal_view():
    compact = re.sub(r"\s+", " ", STYLE_CSS)
    assert 'html[data-view="journal"] .logpanel { display: none; }' in compact


def test_input_dock_has_textarea_and_send_action():
    parser = _parse_journal_view()
    tags = {attrs.get("id"): tag for tag, attrs in parser.input_dock_tags}
    assert tags["journalInputDock"] == "form"
    assert tags["journalTextInput"] == "textarea"
    assert tags["journalSendButton"] == "button"
    assert 'data-i18n-placeholder="journal_input_placeholder"' in INDEX_HTML
    assert 'onsubmit="submitJournalInput(); return false"' in INDEX_HTML
    assert 'onkeydown="onJournalInputKeyDown(event)"' in INDEX_HTML


def test_hidden_placeholder_logic_present():
    """Hidden swaps the whole view for a generic placeholder: CSS does the
    swap, app.js drops fetched content and refetches on Open (defense in
    depth on top of the transport refusing content while Hidden)."""
    compact = re.sub(r"\s+", " ", STYLE_CSS)
    assert (
        'html[data-visibility="hidden"] .journal-sessions, '
        'html[data-visibility="hidden"] .journal-feed-pane { display: none; }'
        in compact
    )
    assert (
        'html[data-visibility="hidden"] .journal-hidden-placeholder '
        "{ display: flex; }" in compact
    )
    assert 'id="journalHiddenPlaceholder"' in INDEX_HTML
    assert "_onJournalVisibilityChanged(payload.mode)" in APP_JS
    assert "_clearJournalContent()" in APP_JS
    assert "_clearJournalMemoryPanel();" in APP_JS


def test_stale_journal_responses_cannot_repopulate_hidden_dom():
    """A sessions/feed response that resolves after Hidden wiped the DOM
    must be dropped: both fetchers capture the content generation before
    their await and bail if _clearJournalContent() bumped it (or Hidden is
    still active) - otherwise the defense-in-depth clear would only hold
    until the in-flight response landed."""
    clear_body = APP_JS.split("function _clearJournalContent()")[1].split("\n}")[0]
    assert "_journalContentGeneration += 1" in clear_body
    sessions_body = APP_JS.split("async function refreshJournalSessions(")[1].split(
        "\n}"
    )[0]
    assert "const generation = _journalContentGeneration;" in sessions_body
    assert (
        "if (generation !== _journalContentGeneration || _isHiddenActive()) return;"
        in sessions_body
    )
    # selectJournalSession must not early-return (task-journal-06: every
    # completion drives the deferred-refetch check), so its stale/Hidden
    # protection gates the render instead.
    feed_body = APP_JS.split("async function selectJournalSession(")[1].split("\n}")[0]
    assert "const generation = _journalContentGeneration;" in feed_body
    assert "generation === _journalContentGeneration && !_isHiddenActive()" in feed_body
    assert "if (valid && _journalSelectedSessionId === sessionId) {" in feed_body


def test_hidden_attribute_actually_hides_journal_placeholders():
    """The feed-pane placeholder has an author display rule, which beats
    the hidden attribute's UA display: none - without an explicit [hidden]
    override the "empty" label keeps its flex: 1 half of the column below
    the feed (observed live 2026-07-17)."""
    compact = re.sub(r"\s+", " ", STYLE_CSS)
    assert ".journal-empty[hidden] { display: none; }" in compact


def test_feed_reanchors_when_a_thumbnail_load_grows_the_scroll_height():
    assert "_reanchorJournalFeedAfterGrowth(image.offsetHeight)" in APP_JS
    body = APP_JS.split("function _reanchorJournalFeedAfterGrowth(")[1].split("\n}")[0]
    assert "feed.scrollTop = feed.scrollHeight;" in body


def _string_catalog(language):
    marker = f"  {language}: {{"
    start = STRINGS_JS.index(marker)
    end = STRINGS_JS.index("\n  },", start)
    body = STRINGS_JS[start:end]
    return dict(re.findall(r'(\w+): "((?:[^"\\]|\\.)*)"', body))


def test_every_new_journal_string_exists_in_both_languages():
    english = _string_catalog("en")
    russian = _string_catalog("ru")
    for key in JOURNAL_STRING_KEYS:
        assert key in english, key
        assert key in russian, key
    assert set(english) == set(russian)


def test_journal_markup_has_no_hardcoded_visible_text():
    """Every text node inside #journalView must come from strings.js via
    data-i18n, so applyUiLanguage() re-stamps all of it."""
    parser = _parse_journal_view()
    assert parser.texts, "journal view markup not found in index.html"
    english = _string_catalog("en")
    for text, owner_attrs in parser.texts:
        key = owner_attrs.get("data-i18n")
        assert key is not None, f"hardcoded journal text: {text!r}"
        assert english[key] == text


def test_journal_rendering_reads_labels_through_ui_strings():
    assert 'uiString("journal_empty_feed")' in APP_JS
    assert 'uiString("journal_no_selection")' in APP_JS
    assert '"journal_source_" + source' in APP_JS


def test_journal_continue_posts_to_the_session_fork_endpoint():
    session_body = APP_JS.split("function _journalSessionElement(")[1].split("\n}")[0]
    assert "continueJournalSession(session.id)" in session_body
    assert "session.id !== _journalActiveSessionId" in session_body
    body = APP_JS.split("async function continueJournalSession(")[1].split("\n}")[0]
    assert '"/api/journal/sessions/" + encodeURIComponent(sessionId) + "/fork"' in body
    assert 'method: "POST"' in body
    assert 'payload.status === "ok"' in body
    assert "selectJournalSession(payload.session_id);" in body


def test_journal_continue_errors_are_localized():
    body = APP_JS.split("function _journalForkErrorMessage(")[1].split("\n}")[0]
    assert 'payload.status === "hidden"' in body
    assert 'payload.reason === "busy"' in body
    assert 'payload.reason === "unknown_session"' in body
    assert 'payload.reason === "oversize_turn"' in body
    assert 'uiString("journal_fork_failed")' in body


def test_journal_new_context_is_an_explicit_journal_action():
    assert 'id="journalNewContextButton"' in INDEX_HTML
    assert 'onclick="startNewJournalContext()"' in INDEX_HTML
    assert 'data-i18n="journal_new_context"' in INDEX_HTML
    body = APP_JS.split("async function startNewJournalContext(")[1].split("\n}")[0]
    assert '"/api/journal/context/new"' in body
    assert 'method: "POST"' in body
    assert "_confirmStartNewJournalContext()" in body
    assert "_journalSelectedSessionId = payload.session_id || null;" in body
    assert "selectJournalSession(payload.session_id);" in body
    assert 'uiString("journal_new_context_ready")' in body


def test_journal_new_context_is_not_the_fork_continue_action():
    new_context_body = APP_JS.split("async function startNewJournalContext(")[1].split(
        "\n}"
    )[0]
    continue_body = APP_JS.split("async function continueJournalSession(")[1].split(
        "\n}"
    )[0]
    assert "/api/journal/context/new" in new_context_body
    assert "/fork" not in new_context_body
    assert "/fork" in continue_body
    assert "/api/journal/context/new" not in continue_body


def test_journal_new_context_errors_are_localized_and_hidden_aware():
    body = APP_JS.split("function _journalNewContextErrorMessage(")[1].split("\n}")[0]
    assert 'payload.status === "hidden"' in body
    assert 'payload.reason === "busy"' in body
    assert 'uiString("journal_new_context_failed")' in body
    start_body = APP_JS.split("async function startNewJournalContext(")[1].split("\n}")[
        0
    ]
    assert "_isHiddenActive()" in start_body
    assert 'uiString("journal_new_context_hidden")' in start_body


def test_journal_memory_panel_is_reachable_from_journal_view():
    assert 'id="journalMemoryToggle"' in INDEX_HTML
    assert 'onclick="toggleJournalMemoryPanel()"' in INDEX_HTML
    assert 'id="journalMemoryPanel"' in INDEX_HTML
    assert 'data-i18n="journal_memory_note"' in INDEX_HTML
    compact = re.sub(r"\s+", " ", STYLE_CSS)
    assert ".journal-memory-panel[hidden] { display: none; }" in compact


def test_journal_memory_panel_loads_and_saves_fixed_file_ids():
    assert 'const _MEMORY_FILE_IDS = ["self", "memory"];' in APP_JS
    load_body = APP_JS.split("async function loadJournalMemoryFiles(")[1].split("\n}")[
        0
    ]
    save_body = APP_JS.split("async function saveJournalMemoryFile(")[1].split("\n}")[0]
    assert '"/api/memory/files/" + fileId' in load_body
    assert '"/api/memory/files/" + fileId' in save_body
    assert 'method: "PUT"' in save_body
    assert "JSON.stringify({ content: savedContent })" in save_body


def test_journal_memory_client_blocks_over_cap_and_preserves_text_on_rejection():
    can_save = APP_JS.split("function _journalMemoryCanSave(")[1].split("\n}")[0]
    assert "state.content.length <= state.maxChars" in can_save
    save_body = APP_JS.split("async function saveJournalMemoryFile(")[1].split("\n}")[0]
    assert "state.content.length > state.maxChars" in save_body
    assert 'payload.reason === "over_limit"' in APP_JS
    assert "savedContent: persistedContent" in save_body


def test_journal_memory_save_preserves_edits_typed_during_inflight_save():
    save_body = APP_JS.split("async function saveJournalMemoryFile(")[1].split("\n}")[0]
    assert "const savedContent = state.content;" in save_body
    assert "const latest = _journalMemoryFiles.get(fileId) || state;" in save_body
    assert (
        "content: latest.content === savedContent ? persistedContent : latest.content,"
        in save_body
    )
    assert "_refreshJournalMemoryFileState(fileId);" in save_body
    assert "_renderJournalMemoryFiles();" not in save_body


def test_journal_memory_typing_updates_existing_dom_without_rerendering_textarea():
    input_body = APP_JS.split("function onJournalMemoryInput(")[1].split("\n}")[0]
    assert "_refreshJournalMemoryFileState(fileId);" in input_body
    assert "_renderJournalMemoryFiles();" not in input_body
    refresh_body = APP_JS.split("function _refreshJournalMemoryFileState(")[1].split(
        "\n}"
    )[0]
    assert ".journal-memory-counter" in refresh_body
    assert ".journal-memory-status" in refresh_body
    assert ".journal-memory-footer button" in refresh_body
    assert "save.disabled = !_journalMemoryCanSave(state);" in refresh_body
    assert "replaceChildren" not in refresh_body


def test_journal_memory_unsaved_changes_guard_navigation_and_unload():
    assert "_confirmDiscardJournalMemoryChanges()" in APP_JS
    assert "journal_memory_discard_confirm" in APP_JS
    assert 'window.addEventListener("beforeunload"' in APP_JS
    body = APP_JS.split("function setActiveView(")[1].split("\n}")[0]
    assert 'view !== "journal"' in body
    assert "_confirmDiscardJournalMemoryChanges()" in body


def test_journal_fork_provenance_detail_uses_text_content():
    body = APP_JS.split("function _journalProvenanceDetail(")[1].split("\n}")[0]
    assert 'event.source !== "fork"' in body
    assert 'uiString("journal_fork_truncated")' in body
    assert "detail.textContent" in body
    assert "innerHTML" not in body


def test_journal_view_has_no_context_menu():
    """Copy is explicit button plus normal text selection; no custom
    context menu is introduced."""
    assert "contextmenu" not in APP_JS


def test_journal_input_posts_json_and_preserves_text_on_rejection():
    body = APP_JS.split("async function submitJournalInput(")[1].split("\n}")[0]
    assert '_journalUrl("/api/journal/input")' in body
    assert 'method: "POST"' in body
    assert "JSON.stringify({ text })" in body
    assert 'if (input.value === text) input.value = "";' in body
    assert 'payload.status === "accepted"' in body
    assert "journal_input_busy" in APP_JS
    assert "journal_input_over_limit" in APP_JS


def test_journal_input_requires_an_explicit_active_context():
    body = APP_JS.split("async function submitJournalInput(")[1].split("\n}")[0]
    assert "_journalActiveSessionId === null" in body
    assert 'uiString("journal_new_context_required")' in body


def test_journal_input_enter_and_shift_enter_contract_is_present():
    body = APP_JS.split("function onJournalInputKeyDown(")[1].split("\n}")[0]
    assert 'event.key !== "Enter" || event.shiftKey' in body
    assert "event.preventDefault();" in body
    assert "submitJournalInput();" in body


def test_search_controls_use_localized_query_and_date_fields():
    assert 'id="journalSearchQuery"' in INDEX_HTML
    assert 'id="journalSearchDateFrom"' in INDEX_HTML
    assert 'id="journalSearchDateTo"' in INDEX_HTML
    assert 'data-i18n-placeholder="journal_search_placeholder"' in INDEX_HTML
    assert 'data-i18n="journal_search_clear"' in INDEX_HTML
    assert "[data-i18n-placeholder]" in STRINGS_JS


def test_search_passes_query_and_optional_date_parameters_to_transport():
    body = APP_JS.split("async function _runJournalSearch(")[1].split("\n}")[0]
    assert 'parameters.set("query", criteria.query);' in body
    assert 'parameters.set("date_from", criteria.dateFrom);' in body
    assert 'parameters.set("date_to", criteria.dateTo);' in body
    assert '"/api/journal/search?" + parameters.toString()' in body


def test_search_snippet_highlighting_uses_text_nodes_not_html_injection():
    body = APP_JS.split("function _appendHighlightedJournalSnippet(")[1].split("\n}")[0]
    assert "document.createTextNode(part)" in body
    assert "mark.textContent = match[1];" in body
    assert "innerHTML" not in body


def test_date_only_search_renders_the_raw_snippet_as_plain_text():
    search_body = APP_JS.split("async function _runJournalSearch(")[1].split("\n}")[0]
    expected_render = (
        "_renderJournalSearchResults(payload ? payload.hits : [], "
        'criteria.query !== "");'
    )
    assert expected_render in search_body
    hit_body = APP_JS.split("function _journalSearchHitElement(")[1].split("\n}")[0]
    assert "if (highlightMatches)" in hit_body
    assert "snippet.textContent = hit.snippet;" in hit_body


def test_search_hit_jumps_to_the_linked_session_turn_and_highlights_it():
    jump_body = APP_JS.split("function _jumpToJournalSearchHit(")[1].split("\n}")[0]
    assert "selectJournalSession(hit.session_id, hit.event_position);" in jump_body
    event_body = APP_JS.split("function _journalEventElement(")[1].split("\n}")[0]
    assert "message.dataset.eventPosition = String(position);" in event_body
    highlight_body = APP_JS.split("function _highlightJournalContextEvent(")[1].split(
        "\n}"
    )[0]
    assert "scrollIntoView" in highlight_body
    assert '"journal-context-hit"' in highlight_body


def test_clearing_search_restores_the_previously_selected_session():
    body = APP_JS.split("function clearJournalSearch(")[1].split("\n}")[0]
    assert "selectJournalSession(_journalSelectedSessionId);" in body
    assert "refreshJournalSessions();" in body
    assert "_clearJournalSearchControls();" in body


def test_clearing_search_without_a_selected_session_replaces_stale_results():
    clear_body = APP_JS.split("function clearJournalSearch(")[1].split("\n}")[0]
    assert "_showJournalNoSelection();" in clear_body
    empty_body = APP_JS.split("function _showJournalNoSelection(")[1].split("\n}")[0]
    assert 'document.getElementById("journalFeed").replaceChildren();' in empty_body
    assert 'uiString("journal_no_selection")' in empty_body


def test_selecting_a_session_while_searching_clears_the_stale_filter_controls():
    body = APP_JS.split("async function selectJournalSession(")[1].split("\n}")[0]
    assert "if (_isJournalSearchActive()) {" in body
    assert "_deactivateJournalSearch();" in body
    assert "_clearJournalSearchControls();" in body


def test_search_input_is_debounced_and_no_results_text_is_localized():
    body = APP_JS.split("function _scheduleJournalSearch(")[1].split("\n}")[0]
    assert "window.setTimeout" in body
    assert "}, 250);" in body
    render_body = APP_JS.split("function _renderJournalSearchResults(")[1].split("\n}")[
        0
    ]
    assert 'uiString("journal_search_no_results")' in render_body
