# Task UI-06: Touchstrip glance surface

**Story:** story-status-console-ui.md
**Статус:** Backlog
**Приоритет:** средний
**Зависимости:** task-ui-01-state-and-event-contract.md,
task-ui-05-open-hidden-visibility-mode.md

## Summary

Design the narrow touch surface as its own UI, not a compressed desktop
dashboard.

## Scope

- Glance page: runtime state, model/backend label, key module dots, visibility
  mode.
- Actions page: Think toggle and context reset with hold-to-confirm.
- Optional activation trigger through orb/touch affordance after warmup story
  lands.
- No dense event log on touchstrip.

## Acceptance Criteria

- [ ] Touch targets are large enough for finger input.
- [ ] Text remains legible on a roughly 900 x 230 class surface.
- [ ] Reset requires hold or equivalent confirmation.
- [ ] Hidden mode suppresses sensitive previews on this surface by default.
- [ ] Same state contract as desktop Status Console is reused.

## Stop Condition

If the chosen GUI framework cannot support this surface without a separate
process or large architecture change, stop and split the touchstrip work into
its own story.
