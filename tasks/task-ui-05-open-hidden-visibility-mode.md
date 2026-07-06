# Task UI-05: Open / Hidden visibility mode

**Story:** story-status-console-ui.md
**Статус:** Backlog
**Приоритет:** средний
**Зависимости:** task-ui-01-state-and-event-contract.md

## Summary

Implement the system visibility mode as a first-class UI and engine state.

## Scope

- `Open`: normal visibility. Voice output and screen preview follow current
  configuration.
- `Hidden`: reduced external visibility. TTS muted/text-only, screen previews
  hidden by default, sensitive snippets not shown on compact surfaces.
- Visibility mode is independent from data locality.
- Color semantics: Open uses cyan/teal; Hidden uses muted violet/slate; amber
  remains warning/cloud/warmup-adjacent.

## Acceptance Criteria

- [ ] UI labels use `Open` / `Hidden`, not `Приватно` / `На людях`.
- [ ] Hidden does not imply cloud/offline status.
- [ ] Hidden behavior is visible in module chips and system events.
- [ ] TTS behavior in Hidden is explicitly tested or manually handed off if it
      touches audio output.
- [ ] Screen preview hiding is default-safe.

## Open Question

Should Hidden change only UI output, or should it also suppress spoken TTS from
ordinary voice turns? This decision affects runtime behavior and must be made
before implementation.

