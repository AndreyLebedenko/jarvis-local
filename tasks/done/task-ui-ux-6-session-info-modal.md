# Task ui-ux-6: Session "Show info" modal

**Status:** Completed 2026-08-14. Implemented and verified by
`python -m pytest` (2039 passed, 1 skipped), `ruff check`,
`ruff format --check`, and `node --check` on app.js; structural UI coverage
in `tests/test_journal_view_ui.py` and the folder-path payload in
`tests/test_ui_transport.py`. Live WebView visual review is the usual
human-run handoff (Browser pane blocks localhost and renders file:// as a
static snapshot in this environment, so scripts do not run - the structural
tests are the accepted substitute). Menu entry is available for all sessions
including the active one (owner-confirmed).
**Lineage:** follows `tasks/done/story-ui-ux-maturity.md` (cards 1-5 shipped);
standalone polish card because that story is closed. Builds directly on
card 2's context-menu seam (`_journalSessionMenuEntries`) and card 1's
overlay pattern (`shortcutsOverlay`).

## Summary

Add a "Показать информацию" / "Show info" entry to the Journal session
context menu that opens a small modal showing the session's name, creation
date-time, on-disk folder path, and total on-disk size, with the folder path
copyable to the clipboard.

## Current boundary

In scope:

- New context-menu entry in `_journalSessionMenuEntries`
  (`src/jarvis/ui/status_console_ui/app.js`), available for every session
  (active included - this is read-only display, not a fork/delete action).
- A modal built on the existing `shortcutsOverlay` pattern: `hidden` toggle,
  `aria-modal="true"`, `_setBackgroundInert`, focus capture/restore, Esc and
  an explicit close control.
- Four fields, rendered in the primary/bright Journal text color (the same
  token as the main feed text, not the dimmed `.journal-session-meta` style):
  - name: `session.title`;
  - created: `session.start_timestamp`, formatted with the existing
    `_formatJournalDate` / `_formatJournalTime`;
  - folder path: absolute path to the session's on-disk folder
    (see backend note below);
  - total size: `_journalUsageBySession.get(session.id)`, formatted with the
    existing `_formatJournalBytes`.
- Folder path is copyable: a copy control reusing `_writeClipboardText` /
  `_copyToClipboardWithJournalStatus` (consistent with the existing
  "Скопировать название"), and the path text is also `user-select: text` so
  plain mouse selection works as the owner asked.
- Backend: extend `journal_session_payload` (the sessions-list payload
  builder) to include the session's absolute folder path
  (`<journal root>/<session_id>`), so the thin client displays a
  server-provided string rather than constructing a filesystem path itself.
- New UI strings in `strings.js` for both the RU and EN catalogs (menu
  label, modal title, the four field labels, copy-path control), per the
  v1.2.11 localization contract.
- CSS for the modal and the bright-text field rows, correct in light and
  dark and consistent with the card-4/5 visual language.

Out of scope:

- No new persistent state, no engine changes, no new destructive action.
- No editing of any field; the modal is display + copy only.
- No new size computation: reuse the usage figure already fetched for the
  session list. If usage has not loaded yet, show the same placeholder the
  list uses, not a blocking fetch.
- No re-layout of the session list or the context menu beyond adding one
  entry.

## Design decisions

- **Path is served as data, not invented by the client.** The absolute
  folder path crosses the transport boundary as a payload field; the client
  never builds a filesystem path from the session id. This keeps the surface
  a thin client per VISION.md and keeps the one source of the journal root
  (the store/history service) authoritative.
- **Hidden mode suppresses it like all journal data.** The path and size
  reach the client only through the sessions endpoint, which already returns
  the hidden response under Hidden mode; the menu entry and modal therefore
  carry no journal data when Hidden. No separate gating logic is added.
- **Copy button plus selectable text, not one or the other.** The owner
  accepts plain text selection as a floor; a copy control is added on top
  for parity with the existing copy-title action, and the path stays
  selectable so both paths work.

## Acceptance criteria

- [ ] The session context menu shows a "Показать информацию" / "Show info"
      entry for every session, including the active one.
- [ ] Selecting it opens a modal showing name, creation date-time, folder
      path, and total size, all in the bright primary Journal text color.
- [ ] The folder path is the correct absolute on-disk path for that session
      and can be copied to the clipboard, and can also be selected with the
      mouse.
- [ ] The modal traps focus, restores focus on close, and closes on Esc and
      on its explicit close control, matching the shortcuts overlay.
- [ ] Under Hidden mode the entry/modal expose no journal data (the sessions
      endpoint returns the hidden response as today).
- [ ] New UI strings exist in both the RU and EN catalogs; no hard-coded
      user-facing text.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green;
      `node --check` passes on the touched `.js`. Structural UI tests
      (`tests/test_journal_view_ui.py`, `tests/test_ui_i18n.py`) cover the
      new entry, modal markup, and i18n keys; a transport test covers the
      new folder-path payload field. Live WebView verification is the usual
      human-run handoff.

## Stop conditions

- Stop if the absolute journal root is not cleanly available at the payload
  layer without threading new configuration through unrelated code.
- Stop if adding the folder-path field to the sessions payload turns out to
  require changing the `JournalSessionSummary` contract in a way other
  consumers depend on (it should be an additive payload field, not a summary
  reshape).

## Verification

- Automated: `tests/test_journal_view_ui.py`, `tests/test_ui_i18n.py`, a
  transport payload test, `python -m pytest`, Ruff, `node --check`.
- Manual handoff (human-run, live WebView): open the menu on a session,
  confirm the four values are correct and bright, copy the path and paste it
  elsewhere, select the path with the mouse, Esc/close behavior, and Hidden
  suppression.
