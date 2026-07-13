# Backlog: visibility-toggle has the same non-authoritative initial state

**Status:** Backlog.
**Source:** story-v1.3.1 task 4 review (2026-07-13), while fixing the
identical bug in the reasoning-level segmented control.

## Summary

`index.html`'s `#visibilityToggle` hardcodes `class="sel"` on the "Open"
button, the same pattern just fixed for `#reasoningLevelToggle`'s "Off"
button. Reopening/reloading the Status Console while Jarvis is running in
Hidden mode (not a process restart) will flash "Open" as selected until the
real snapshot arrives and `applyVisibilityMode()` corrects it.

## Context

story-v1.3.1 task 4 required "Do not update the selected option
optimistically... update it only from the authoritative snapshot or delta"
for the reasoning-level control, and a review caught that the static markup
preselected "Off" regardless of the engine's real state. The same
mechanical bug exists in `#visibilityToggle` (task-ui-05, unrelated story) -
not touched here since it is out of story-v1.3.1's boundary and no story
task currently owns visibility-toggle markup.

## Current Boundary

- Do not fold into story-v1.3.1; that story is otherwise complete.
- Fix is mechanical and small: remove `class="sel"` from the "Open" button
  in `index.html`, matching the reasoning-level-toggle fix exactly.

## Acceptance Criteria

- [ ] `index.html`'s `#visibilityToggle` "Open" button has no hardcoded
      `sel` class in the static markup.
- [ ] A static test (mirroring
      `test_reasoning_level_toggle_has_no_optimistic_initial_selection` in
      `tests/test_status_console.py`) pins this for `#visibilityToggle`.
- [ ] `python -m pytest` passes.
