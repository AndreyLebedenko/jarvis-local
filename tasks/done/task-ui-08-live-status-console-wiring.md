# Task UI-08: Live Status Console wiring

**Story:** follow-up to done/story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** высокий
**Зависимости:** done/story-status-console-ui.md

## Summary

Wire the completed Status Console surfaces into the real Jarvis process, so the
desktop console can run against the live engine instead of only the manual demo
harness.

## Scope

- Add an explicit launch path for Jarvis with the desktop Status Console.
- Share one `StatusConsoleApi` with the touchstrip surface when touchstrip is
  enabled.
- Push live engine state that already has an authoritative source:
  data locality, model label, Think mode, Open/Hidden visibility mode, system
  events, microphone sleep/wake status, and coarse runtime state.
- Keep the existing headless launch path available.
- Document the launch command.

## Out of Scope

- Real module-health probes. The completed story explicitly deferred the
  authoritative source for `ModuleHealth`; this task must not fake `OK` health.
- New module lifecycle/reset APIs.
- Changing Hidden-mode semantics.
- Reworking hotkey provider architecture.

## Stop Condition

If `pywebview.start()` cannot run the UI loop and Jarvis's `asyncio` runtime in
one process using the already-verified callback pattern from
`manual_check_status_console.py`, stop and split this into a larger GUI-runtime
architecture task.

## Acceptance Criteria

- [x] `python main.py --status-console` opens the live Status Console and runs
      Jarvis.
- [x] The existing `python main.py` headless path remains available.
- [x] System events from `publish_system_event()` appear in the desktop panel.
- [x] Think and Open/Hidden controls round-trip through the real engine state.
- [x] The implementation does not invent module health status without a real
      source.
- [x] Automated pure-logic tests pass; live WebView/hotkey/audio verification is
      handed to the human per project protocol.

## Implementation Notes

- `main.py --status-console` creates the desktop window and, by default, the
  touchstrip window before `webview.start()`, sharing one `StatusConsoleApi`.
- `--no-touchstrip` keeps the live run to the desktop Status Console only.
- `wire_status_console()` subscribes to real bus events and pushes snapshots to
  the UI without adding fake module-health data.
- The microphone chip is updated from the real `MicSleepToggled` event:
  asleep -> `UNAVAILABLE` / `усыплён`, awake -> `OK` / `слушает`.
- `PROJECT.md`, `README.md`, and `README.ru.md` document the new live launch
  path.

## Verification

- `python main.py --help`
- `python -m pytest` - 267 passed.

## Manual Handoff

Run from an elevated terminal on the Windows workstation:

```bash
python main.py --status-console
```

Expected: the desktop Status Console and touchstrip windows open, Jarvis warms
the configured Ollama model, system events appear in the desktop event panel,
and Think/Open-Hidden controls update from real engine events. To test only the
desktop window:

```bash
python main.py --status-console --no-touchstrip
```
