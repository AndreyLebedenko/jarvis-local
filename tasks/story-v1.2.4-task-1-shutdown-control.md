# Task: Status Console shutdown control

**Story:** `tasks/story-v1.2.4-status-console-control-plane.md`
**Status:** Backlog.
**Release:** v1.2.4

## Summary

Add a guarded Shutdown control to the live Status Console and route it through
the existing clean shutdown path.

After `python main.py --status-console` starts the live WebView windows, the UI
has controls for Think, Open/Hidden, context reset, and module reset requests,
but no visible way to stop the running engine. If the shutdown hotkey is not
convenient or does not fire, the user currently falls back to killing
`python.exe`, which bypasses normal cleanup.

## Current Boundary

- Use the same shutdown path as the existing shutdown hotkey.
- Do not add process kill fallback.
- Do not add process supervisor/restart UI, change the shutdown hotkey, or add
  OS tray integration.
- Decide whether the touchstrip also gets a shutdown action; if yes, make it
  hard to trigger accidentally.
- Lifecycle controller is created only if the stop condition triggers.

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
