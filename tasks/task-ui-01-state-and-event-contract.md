# Task UI-01: State and event contract for Status Console

**Story:** story-status-console-ui.md
**Статус:** Backlog
**Приоритет:** высокий
**Зависимости:** нет

## Summary

Define the backend-to-UI contract before building screens. The UI must consume
structured state/events, not scrape logs or infer state from unrelated module
internals.

## Scope

- Define runtime state enum: `IDLE`, `WARMING`, `LISTENING`, `THINKING`,
  `SPEAKING`, `ERROR`.
- Define module health snapshot shape for backend/model, microphone, TTS,
  memory and vision/screen.
- Define system event shape: timestamp, source, level, message, optional
  correlation id.
- Define visibility mode state: `Open` / `Hidden`.
- Define data locality state separately from visibility mode.

## Acceptance Criteria

- [ ] Contract is documented in a task/story document before implementation.
- [ ] Existing events (`MicSleepToggled`, `ThinkingModeToggled`,
      `ResponseToken`, screenshot/clipboard events) are mapped where relevant.
- [ ] Missing events are explicitly listed as implementation requirements.
- [ ] Reasoning chunks are excluded from UI events by default.
- [ ] Contract includes test boundaries for pure logic.

## Stop Condition

If the existing event bus cannot express the UI contract without broad event
schema changes, stop and update `PROJECT.md`/story boundaries before coding.

