# Task journal-07: Search UI with date filter

**Status:** Planned.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`
**Depends on:** task-journal-05. (Playback from -06 not required.)

## Summary

Wire the search field and date-range filter above the feed to the search
endpoint: results as a filtered feed with match highlighting and a
jump-to-session-context action.

## Context you need

- Story card "UI/UX" search paragraph and the known FTS5 Russian-stemming
  limitation (exact/prefix match only - do not try to fix it here).
- task-journal-04's search endpoint (query + date range, hits link to
  session + position).
- `src/jarvis/ui/status_console_ui/` layout from task-journal-05.

## Boundary

- Changes limited to `src/jarvis/ui/status_console_ui/` and tests.
- Search hits assistant answers only (that is all the index contains in
  v1.5.0); the UI must not imply user turns are searchable.
- No semantic search, no morphology, no index changes.

## Requirements

- Search field + date-from/date-to controls above the feed; empty query
  with a date range is valid (session-by-date browsing).
- Results render as a filtered feed of matching answer snippets with the
  matched terms highlighted, grouped under their session header.
- Clicking a hit opens that session in the normal feed, scrolled to the
  matching turn, briefly highlighted.
- Clearing search restores the previous session view.
- Debounce input; empty state and "no results" state have proper en/ru
  strings via `strings.js`.
- While Hidden, search is unavailable exactly like the rest of the
  Journal view (placeholder covers it; transport already refuses).

## Acceptance criteria

- [ ] Structural/logic tests: query+date parameters passed correctly;
      highlight rendering escapes HTML (a snippet containing markup must
      not inject); jump-to-context targets the right turn; clear
      restores state.
- [ ] en/ru strings complete; no hardcoded literals.
- [ ] `python -m pytest` green.
- [ ] Human-run handoff prepared: search a known Russian answer by exact
      and prefix form, filter by a date range, jump to context.
