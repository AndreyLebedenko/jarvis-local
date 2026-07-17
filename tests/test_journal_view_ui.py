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
    "journal_source_assistant",
)


class _JournalViewParser(HTMLParser):
    """Collects the element tree and text nodes of #journalView."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.texts = []  # (text, owning tag attrs) for text inside the view
        self.input_dock_depth = None
        self.input_dock_content = []
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
        if self.input_dock_depth and data.strip():
            self.input_dock_content.append(data.strip())


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


def test_input_dock_exists_and_is_empty():
    parser = _parse_journal_view()
    assert 'id="journalInputDock"' in INDEX_HTML
    assert parser.input_dock_content == []


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


def test_stale_journal_responses_cannot_repopulate_hidden_dom():
    """A sessions/feed response that resolves after Hidden wiped the DOM
    must be dropped: both fetchers capture the content generation before
    their await and bail if _clearJournalContent() bumped it (or Hidden is
    still active) - otherwise the defense-in-depth clear would only hold
    until the in-flight response landed."""
    clear_body = APP_JS.split("function _clearJournalContent()")[1].split("\n}")[0]
    assert "_journalContentGeneration += 1" in clear_body
    for function_name in ("refreshJournalSessions", "selectJournalSession"):
        body = APP_JS.split(f"async function {function_name}(")[1].split("\n}")[0]
        assert "const generation = _journalContentGeneration;" in body
        assert (
            "if (generation !== _journalContentGeneration || _isHiddenActive()) return;"
            in body
        )


def test_feed_reanchors_when_a_thumbnail_load_grows_the_scroll_height():
    assert '_reanchorJournalFeedAfterGrowth(image.offsetHeight)' in APP_JS
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


def test_journal_view_is_read_only_in_this_task():
    """No interactive content in the dock and no playback controls: the
    only journal onclick/controls are the session rows built in app.js."""
    assert "journalInputDock" not in APP_JS
    assert "probe.controls" not in APP_JS
    assert re.search(r"journal-audio[^\n]*addEventListener\(\"click\"", APP_JS) is None
