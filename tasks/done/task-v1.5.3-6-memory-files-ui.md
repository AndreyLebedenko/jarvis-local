# Task v1.5.3-6: Memory files UI

**Status:** Completed.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** task-v1.5.3-5 (read/write API).

## Summary

Add a memory panel to the Journal-view surface where the user can read
and edit memory.md and self.md within their caps. UI only.

## Context you need

- `src/jarvis/ui/status_console_ui/`: view structure (`index.html`
  views, `app.js` view switching, token fetch pattern, `strings.js`).
- Cross-cutting rule 10: memory editing enters through the Journal
  view's surface - a panel reachable from the Journal view, not a new
  window or a Control Center tab.
- task-v1.5.3-5's response contract (content, cap, size, over-cap
  rejection shape).

## Boundary

- Plain-text editing of the two files; no Markdown preview, no diff
  view, no version history.
- No autosave: explicit save action per file.
- Hidden mode: suppressed with the journal surface.

## Requirements

- The panel shows both files with localized titles and a short
  description of each file's role (durable facts vs persona), current
  size against the cap, and an editor per file.
- Save sends the full content; over-cap input is blocked client-side
  with a live character count and the server rejection is still
  handled gracefully (no data loss of the edited text).
- A note in the panel states that changes apply from the next session
  start (matching task-4's sampling contract), so edits not affecting
  the live session is expected behavior, not a bug.
- Unsaved-changes state is visible; navigating away with unsaved edits
  asks before discarding.
- All new strings go through the localization catalog (ru/en).

## Acceptance criteria

- [ ] Pure logic factored testably (size counting, state mapping) has
      tests.
- [ ] Human-run manual handoff covers: edit and save both files,
      content survives app restart and is audibly reflected in a next
      session's answers (memory fact recall), over-cap blocking,
      unsaved-changes guard, and Hidden suppression.
- [ ] `python -m pytest` and Ruff checks are green.
