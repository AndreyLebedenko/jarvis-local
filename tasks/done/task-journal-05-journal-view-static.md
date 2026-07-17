# Task journal-05: Journal view in the Status Console (static)

**Status:** Planned.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`
**Depends on:** task-journal-04.

## Summary

Add the Journal view to the Status Console UI: `Console | Journal`
switcher, session list, read-only feed rendering. Static in the sense of
"no live updates, no playback, no search yet" - those are tasks 06/07.

## Context you need

- Story card section "UI/UX" - it is the spec for this task; follow it
  point by point.
- `docs/screenshots/en/status-console.jpg` - the current look; match its
  visual language (dark palette, chips, segmented controls).
- `src/jarvis/ui/status_console_ui/`: `index.html`, `style.css`,
  `app.js`, `contract.js`, `transport.js`, `strings.js`. Vanilla
  HTML/CSS/JS, system font stack, no CDN, no framework - keep it that
  way (story boundary and existing project rule).
- `strings.js`: all user-visible text goes through it (en/ru).
- Existing structural JS tests in `tests/` parse UI source; mirror them.

## Boundary

- Changes limited to `src/jarvis/ui/status_console_ui/` and tests.
- Read-only: no input controls that send anything. The input dock is
  rendered as an empty reserved element at the bottom of the feed
  (layout participates in scrolling), with no interactive content.
- Audio tiles render (icon, duration, filename) but play is inert in
  this task (task-journal-06 wires it). Do not add right-click behavior.
- No live WS handling for `journal_event` yet.

## Requirements

- Header gains a `Console | Journal` segmented control styled like
  Open/Hidden. Console view stays pixel-identical when selected.
- Journal view replaces the central column; System Events panel is
  hidden while Journal is active.
- Left: session list (date, start time, duration, title) from the
  sessions endpoint, newest first, current selection highlighted.
- Right: feed of the selected session - user turns right, Jarvis left;
  voice = audio tile with duration; clipboard = text with a source mark;
  screenshots = thumbnail via the media endpoint; assistant = text.
  Bottom-anchored scrolling above the reserved input dock.
- Hidden mode: the whole Journal view swaps to a generic placeholder
  (same pattern as the vision chip detail); restored on Open. The UI
  additionally relies on the transport already refusing content while
  Hidden (task-journal-04) - defense in depth, not either/or.
- en/ru strings for every new label.

## Acceptance criteria

- [ ] Structural tests: switcher exists and toggles view visibility;
      System Events hidden in Journal view; input dock element exists
      and is empty; Hidden placeholder logic present in `app.js`.
- [ ] All new user-visible strings come from `strings.js` (test parses
      for hardcoded literals in new code).
- [ ] `python -m pytest` green.
- [ ] Human-run visual check handoff prepared: exact steps to open the
      console with a populated journal root and what to verify (layout,
      both languages, Hidden behavior, responsive rule).
