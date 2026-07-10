# Task: Hotkey manual verification handoff

**Story:** `tasks/story-v1.2.6-hotkey-provider-migration.md`
**Status:** Completed.
**Release:** v1.2.6
**Depends on:** `tasks/story-v1.2.6-task-3-hotkey-dependency-docs.md`

## Summary

Prepare human-run verification for native global hotkeys on the real Windows
machine.

## Current Boundary

- Handoff instructions and optional check script only.
- The agent does not run global hotkey hardware checks.
- Do not close the release story until the human reports results.

## Acceptance Criteria

- [x] Handoff covers Administrator and non-Administrator behavior.
- [x] Handoff covers focus-independent hotkey triggering.
- [x] Handoff covers registration conflict behavior.
- [x] Handoff covers each migrated hotkey.
- [x] Handoff explains what output or observations to report.
- [x] Automated pure tests pass before handoff.

## Verification

- Run `python -m pytest`.
- Human runs the documented checks and reports results.

## Human handoff

Run the matrix once from a normal PowerShell terminal and once from an
Administrator PowerShell terminal. Close every other Jarvis/manual hotkey
process before each run.

### 1. Isolated registration and focus independence

```powershell
python manual/manual_check_hotkey_provider.py ctrl+alt+q
```

Expected startup output is `REGISTERED: ctrl+alt+q`. Focus a different
application and press `Ctrl+Alt+Q`; the probe terminal must print
`FIRED: ctrl+alt+q`. Return to the terminal and press `Ctrl+C`; it must print
`UNREGISTERED: ctrl+alt+q` without a traceback. Report the privilege mode and
all three observations.

### 2. Registration conflict

Leave the first probe running. In a second terminal with the same privilege
mode run the same command. The second process must fail immediately with a
clear `HotkeyError` naming `ctrl+alt+q` as already registered. Stop the first
probe, then start the second command again; registration must now succeed.
Report both outputs. A traceback is acceptable only as the presentation of the
expected named `HotkeyError`; a hang or generic Win32/ctypes error is not.

### 3. All migrated hotkeys

Run Jarvis with a different application focused while pressing each shortcut:

```powershell
python main.py --status-console --no-touchstrip
```

Record `PASS`, `FAIL`, or `BLOCKED` plus the visible/audible observation for:

- `Ctrl+Alt+S`: full-screen capture is accepted for the next request.
- `Ctrl+Alt+R`: region overlay opens; select a non-empty region. If the known
  Tkinter callback-thread issue appears, record `BLOCKED` with its traceback
  and reference `tasks/backlog/region-select-overlay-threading.md`; do not fix
  it under this task.
- `Ctrl+Alt+V`: clipboard text is submitted and the clipboard cue plays.
- `Ctrl+Alt+M`: microphone sleep/wake toggles and the matching cue plays on
  two consecutive presses.
- `Ctrl+Alt+T`: thinking mode toggles on/off and the Status Console reflects
  both transitions.
- `Ctrl+Alt+Q`: clean shutdown reaches `Shutdown: teardown complete` with no
  error or traceback.

Also report whether the non-Administrator startup warning appeared. Do not
enter secrets in the clipboard or capture sensitive screen content during the
check.

## Stop Conditions

- Stop if manual checks reveal provider behavior that conflicts with the
  documented architecture.
- Stop if failures are caused by OS/environment issues outside the task.
