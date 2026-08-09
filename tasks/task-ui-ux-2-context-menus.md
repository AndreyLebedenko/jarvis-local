# Task: Context menus - reusable menu component, existing-action wiring

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Proposed. Depends on task 1 (uses its focus/keymap/listbox
primitives).
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-09.
**Scope class:** front-end only (`status_console_ui/*.js`, `*.css`,
`strings.js`). No control commands, no transport, no engine changes.

## Summary

There is no context-menu component in the UI. The owner asked for a
right-mouse-button menu on list items offering the relevant actions. All
such actions already exist as buttons or endpoints scattered across each
item's row (e.g. Journal sessions already have Continue/Delete buttons and
per-answer Copy; tool rows have an enable checkbox). This task
consolidates those into one reusable menu without adding any new
capability.

## Proposed direction

1. One reusable menu component: a `role="menu"` popup positioned at the
   pointer (right-click) or the focused item (`Shift+F10` and a visible
   per-item menu button, so it is reachable without a mouse). Arrow keys
   move between `role="menuitem"`s, Enter/Space activate, `Esc` closes and
   restores focus to the item (via task 1's keymap `Esc` stack). Only one
   menu open at a time.

2. Per-item action sets, drawn strictly from existing commands/endpoints:
   - **Journal session**: Continue (fork), Delete, Copy title. (Continue
     and Delete already exist as row buttons; Copy title is a local
     clipboard action like the existing `copyJournalAnswer`.)
   - **Journal feed message**: Copy (existing `copyJournalAnswer`),
     Generate transcript, Generate annotation (existing endpoints).
   - **Tool row**: Enable/Disable (existing `set_tool_enabled` send),
     Copy tool name.
   - **Module chip**: include Reset **only if** a real engine reset
     exists; today `reset_module` is a "not implemented" stub, so a Reset
     menu item is omitted rather than shown as a dead action.

3. Actions that would require a capability the engine does not already
   expose are not added.

Menu labels are localized through `strings.js` in en and ru.

## Boundary

- No new control commands, transport routes, or engine capabilities. If an
  action is not already reachable, it is dropped, not built.
- Menus appear only on the item types listed above; the Status view's
  chips get no menu in this story.
- Right-click anywhere else keeps default behavior (or the browser
  default), except it is suppressed on items that own a menu.

## Acceptance criteria

- [ ] One reusable menu component, opened by right-click, `Shift+F10`, and
      a visible per-item menu button; keyboard-navigable (`role="menu"`/
      `menuitem`, arrows, Enter/Space, `Esc` closes and restores focus).
- [ ] Only one menu open at a time; opening another or clicking away
      closes the current one.
- [ ] Session, feed-message, and tool-row menus offer exactly the
      existing-capability actions listed above and each action works.
- [ ] No Reset menu item while `reset_module` is a stub.
- [ ] Menu labels exist in both `en` and `ru` catalogs.
- [ ] Browser-preview handoff prepared: open each menu type by mouse and by
      keyboard and invoke one action from each.
- [ ] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

(to be filled at completion)
