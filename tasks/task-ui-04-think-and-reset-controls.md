# Task UI-04: Think and reset controls

**Story:** story-status-console-ui.md
**Статус:** Backlog
**Приоритет:** высокий
**Зависимости:** task-ui-01-state-and-event-contract.md

## Summary

Add the minimal controls the first UI needs: Think toggle, context reset and
per-module reset requests.

## Scope

- Think toggle mirrors existing `ThinkingModeState`.
- Global reset is labeled as context/conversation reset and requires
  confirmation.
- Per-module reset controls are explicit: STT/microphone, backend/model, TTS,
  memory, vision/screen.
- Reset actions are engine requests with visible system events.

## Acceptance Criteria

- [ ] Think toggle preserves existing semantics: sampled at next accepted turn,
      not mid-stream.
- [ ] UI never displays reasoning text or `message.thinking`.
- [ ] Global context reset confirms before destructive action.
- [ ] Module reset failure is reported in system events.
- [ ] Controls have testable pure-logic handlers where possible.

## Stop Condition

If a module has no lifecycle/reset API, do not fake success in UI. Stop and
record the missing engine capability.

