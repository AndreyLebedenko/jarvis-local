# Task UI-03: System events panel

**Story:** story-status-console-ui.md
**Статус:** Backlog
**Приоритет:** высокий
**Зависимости:** task-ui-01-state-and-event-contract.md

## Summary

Expose engine activity in the UI so the user does not need to inspect Windows
console output.

## Scope

- Display recent events in reverse chronological or live-appending order.
- Show timestamp, source, level and message.
- Support sources such as `ENGINE`, `VAD`, `STT`, `LLM`, `TTS`, `CAPTURE`,
  `HOTKEY`, `CONFIG`, `WARMUP`.
- Support levels `INFO`, `ACTIVE`, `WARN`, `ERROR`.
- Keep event text concise and user-readable.

## Acceptance Criteria

- [ ] Events are fed through structured logging/events, not console scraping.
- [ ] Warnings/errors are visually distinct without overwhelming normal state.
- [ ] Warmup success/failure is visible.
- [ ] Think on/off and mic sleep/wake remain log-visible.
- [ ] Event panel handles long messages without layout breakage.

## Stop Condition

If logs and bus events diverge as competing sources of truth, stop and define
which layer owns UI-visible events before implementation.

