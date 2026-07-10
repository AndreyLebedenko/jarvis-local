# Task: Push-to-talk hotkey trigger

**Story:** `tasks/story-v1.2.7-activation-and-warmup.md`
**Status:** Backlog.
**Release:** v1.2.7
**Depends on:** `tasks/story-v1.2.7-task-2-warming-runtime-state.md`

## Summary

Add push-to-talk activation through the unified HotkeyProvider path.

## Current Boundary

- Use HotkeyProvider; do not add a separate hotkey mechanism.
- Real global behavior is a human handoff.
- The provider interface must not expose Windows-specific details to callers.
- Linux provider implementation is out of scope.

## Acceptance Criteria

- [ ] Push-to-talk hotkey is configurable.
- [ ] Trigger calls the same activation path as other future triggers.
- [ ] Registration conflict is visible in log/UI.
- [ ] Callback schedules work onto the asyncio loop.
- [ ] The trigger uses the existing provider path without reintroducing a
      legacy global-key-hook listener.
- [ ] Tests cover synthetic trigger behavior without real keyboard hardware.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Prepare manual handoff for real global PTT behavior.

## Stop Conditions

- Stop if HotkeyProvider migration has not landed.
- Stop if implementation would create a long-lived mixed privacy model.
