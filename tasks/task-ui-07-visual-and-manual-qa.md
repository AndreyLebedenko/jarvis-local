# Task UI-07: Visual and manual QA for Status Console

**Story:** story-status-console-ui.md
**Статус:** Backlog
**Приоритет:** средний
**Зависимости:** task-ui-02-desktop-status-console-shell.md,
task-ui-03-system-events-panel.md, task-ui-04-think-and-reset-controls.md,
task-ui-05-open-hidden-visibility-mode.md, task-ui-06-touchstrip-glance-surface.md

## Summary

Verify the first UI visually and manually where hardware/audio/window-system
behavior is involved.

## Scope

- Desktop screenshots at normal and narrow widths.
- Touchstrip layout screenshot or equivalent render.
- State transition walkthrough: idle, warming, listening, thinking, speaking,
  error.
- Manual checks for TTS mute/Hidden behavior and global hotkey interaction.
- Confirm no network-loaded UI assets.

## Acceptance Criteria

- [ ] No text overlap in desktop or touchstrip layouts.
- [ ] All state colors and labels match the story semantics.
- [ ] Hidden mode behavior is confirmed manually if audio/screen output is
      involved.
- [ ] System events visibly report warmup, reset and Think transitions.
- [ ] Manual handoff commands are documented.

## Stop Condition

If visual QA reveals that the first shell cannot fit the required controls
without redesign, stop and revise the UI task boundaries instead of adding
workarounds.

