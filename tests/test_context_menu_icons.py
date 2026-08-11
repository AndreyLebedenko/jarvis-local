"""task-ui-ux-5: the Copy icon on context-menu entries.

Source-text checks only, same approach as tests/test_journal_live_ui.py -
no browser, no JS runtime (Testing protocol). This file exists because a
first pass of task-ui-ux-5 shipped without one: stop-time review caught
that Copy title/Copy name had regressed to text-only with nothing to
catch it. These pin both the generic mechanism (interaction.js's
entry.icon support) and each of the three call sites that use it.
"""

from jarvis.ui.status_console import UI_DIR

APP_JS = (UI_DIR / "app.js").read_text(encoding="utf-8")
INTERACTION_JS = (UI_DIR / "interaction.js").read_text(encoding="utf-8")


def _function_body(source, name, prefix="function "):
    return source.split(f"{prefix}{name}(")[1].split("\n}")[0]


def _entry_block(body, marker):
    """The single return-array entry containing marker, isolated by
    splitting on the entry's own closing '},' - mirrors how these arrays
    are laid out (one entry per line group) in app.js."""
    return body.split(marker)[1].split("},")[0]


def test_open_context_menu_prepends_an_optional_entry_icon():
    """interaction.js stays icon-shape-agnostic (see its header comment):
    it only knows an entry may carry a prebuilt DOM node to prepend,
    never what an icon looks like or where its path data lives."""
    body = _function_body(INTERACTION_JS, "openContextMenu")
    assert "if (entry.icon) item.appendChild(entry.icon);" in body
    assert "label.textContent = entry.label;" in body
    icon_at = body.index("if (entry.icon)")
    label_at = body.index("label.textContent = entry.label;")
    assert icon_at < label_at


def test_tool_row_copy_name_entry_carries_the_copy_icon():
    body = _function_body(APP_JS, "_toolRowMenuEntries")
    entry = _entry_block(body, 'uiString("tool_row_copy_name")')
    assert 'icon: _icon("copy")' in entry


def test_journal_session_copy_title_entry_carries_the_copy_icon():
    body = _function_body(APP_JS, "_journalSessionMenuEntries")
    entry = _entry_block(body, 'uiString("journal_session_copy_title")')
    assert 'icon: _icon("copy")' in entry


def test_journal_message_copy_answer_menu_entry_carries_the_copy_icon():
    """The feed message's "..." menu duplicates its own standalone
    .journal-copy button (see app.js's _journalEventElement) - both use
    the same copy icon for the same action."""
    body = _function_body(APP_JS, "_journalMessageMenuEntries")
    entry = _entry_block(body, 'uiString("journal_copy_answer")')
    assert 'icon: _icon("copy")' in entry
