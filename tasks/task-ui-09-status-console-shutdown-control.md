# Task UI-09: Status Console shutdown control

**Story:** follow-up to done/story-status-console-ui.md
**Статус:** Backlog.
**Приоритет:** высокий
**Зависимости:** done/task-ui-08-live-status-console-wiring.md

## Summary

Add a real Shutdown control to the live Status Console so the user can stop
Jarvis cleanly from the UI instead of killing the Python process from Task
Manager.

## User Problem

After `python main.py --status-console` starts the live WebView windows, the UI
has controls for Think, Open/Hidden, context reset, and module reset requests,
but no visible way to stop the running engine. If the shutdown hotkey is not
convenient or does not fire, the user currently falls back to killing
`python.exe`, which bypasses normal cleanup.

## Scope

- Add a Shutdown button/control to the desktop Status Console.
- Route the control through `StatusConsoleApi` into the real asyncio loop.
- Trigger the same clean shutdown path as the existing shutdown hotkey:
  background tasks are cancelled, pending TTS/sound cues are awaited, bus
  subscriptions are removed, and hotkeys are unregistered.
- Show a visible system event or runtime state change when shutdown is
  requested.
- Decide whether the touchstrip also gets a shutdown action, and if yes, make
  it hard to trigger accidentally.

## Out of Scope

- Force-kill fallback for wedged hardware/audio drivers.
- Process supervisor/restart UI.
- Changing the existing shutdown hotkey.
- OS tray integration.

## Stop Condition

If the current shutdown path cannot be triggered from `StatusConsoleApi`
without creating a circular dependency between UI wiring and `run()` lifecycle
ownership, stop and split out a small lifecycle controller abstraction instead
of threading ad-hoc callbacks through unrelated modules.

## Acceptance Criteria

- [ ] Desktop Status Console exposes a clear Shutdown control.
- [ ] Clicking Shutdown requires confirmation or another deliberate guard.
- [ ] The control stops Jarvis through the same clean path used by the shutdown
      hotkey, not by calling `os._exit()` or killing the process.
- [ ] A shutdown request is visible in the system events panel before teardown
      starts when the panel is still available.
- [ ] Automated pure-logic tests cover the JS -> Python -> shutdown signal path.
- [ ] Manual handoff explains how to verify clean shutdown from the real
      WebView window.
