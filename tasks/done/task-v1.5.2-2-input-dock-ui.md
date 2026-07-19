# Task v1.5.2-2: Journal input dock UI

**Status:** Completed.
**Story:** `tasks/done/story-v1.5.2-journal-ux-pack.md`
**Depends on:** task-v1.5.2-1 (the endpoint must exist).

## Summary

Fill the reserved Journal input dock with a working text input: a text
field and a send action that POSTs to the v1.5.2-1 endpoint and shows
the structured result. UI only.

## Context you need

- `src/jarvis/ui/status_console_ui/index.html`: the reserved
  `#journalInputDock` element; `style.css` has the reserved
  `.journal-input-dock` block.
- `src/jarvis/ui/status_console_ui/app.js`: the journal view code reads
  the auth token from the URL query and appends it to fetch calls -
  reuse that exact pattern; the feed updates live via `journal_event`
  WS pushes, so the sent message needs no manual feed insertion.
- `src/jarvis/ui/status_console_ui/strings.js`: localization catalog;
  all new visible text goes through it (ru/en).
- Hidden mode: the journal view is replaced by a placeholder; the dock
  must be part of that suppression, not a leftover interactive control.

## Boundary

- No attach control, no drag-and-drop, no file input of any kind (that
  is v1.6.0 scope); do not add placeholder UI for them.
- No feed re-layout; the dock uses its reserved space.
- No new transport endpoints or protocol changes.

## Requirements

- Text field plus send control in the dock; Enter sends, Shift+Enter
  makes a newline.
- Send POSTs to the endpoint with the token; while the request is in
  flight the send control is disabled (no double submit).
- A busy/Hidden/over-limit rejection shows a localized, non-blocking
  message and preserves the typed text; an accepted send clears the
  field.
- The dock is disabled or hidden entirely while Hidden mode is active,
  consistent with the journal placeholder behavior.
- All new strings live in the localization catalog for both languages.

## Acceptance criteria

- [x] Automated tests pin whatever pure logic exists (e.g. request
      payload construction or response-to-message mapping) if it is
      factored testably; DOM behavior itself is manual scope.
- [x] A human-run manual handoff script/checklist covers: send by
      button and by Enter, newline by Shift+Enter, busy rejection
      feedback, Hidden mode suppression, and the answer appearing in
      the live feed and aloud.
- [x] `python -m pytest` and Ruff checks are green.
