# Task: Status Console shutdown control

**Story:** `tasks/story-v1.2.4-status-console-control-plane.md`
**Status:** Backlog.
**Release:** v1.2.4
**Detailed card:** `tasks/task-ui-09-status-console-shutdown-control.md`

## Summary

Add a guarded Shutdown control to the live Status Console and route it through
the existing clean shutdown path.

## Current Boundary

- Start from `tasks/task-ui-09-status-console-shutdown-control.md`.
- Use the same shutdown path as the existing shutdown hotkey.
- Do not add process kill fallback.
- Lifecycle controller is created only if the detailed card stop condition
  triggers.

## Acceptance Criteria

- [ ] Desktop Status Console exposes a clear Shutdown control.
- [ ] Shutdown requires confirmation or another deliberate guard.
- [ ] Shutdown request is visible in system events before teardown when
      possible.
- [ ] Clean shutdown cancels tasks, awaits pending TTS/sound cues,
      unsubscribes bus handlers, and unregisters hotkeys.
- [ ] Automated pure tests cover JS to Python to shutdown signal path.
- [ ] Manual WebView handoff is prepared.

## Verification

- Run `python -m pytest`.
- Prepare exact manual command for real WebView shutdown verification.

## Stop Conditions

- Stop if routing shutdown through `StatusConsoleApi` creates a circular
  dependency with `run()` lifecycle ownership.
- Stop if clean shutdown cannot be reached without ad-hoc callbacks through
  unrelated modules.
