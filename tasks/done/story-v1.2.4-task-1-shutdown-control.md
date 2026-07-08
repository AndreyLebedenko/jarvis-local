# Task: Status Console shutdown control

**Story:** `tasks/done/story-v1.2.4-status-console-control-plane.md`
**Status:** Completed.
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

- [x] Desktop Status Console exposes a clear Shutdown control.
- [x] Shutdown requires confirmation or another deliberate guard.
- [x] Shutdown request is visible in system events before teardown when
      possible.
- [x] Clean shutdown cancels tasks, awaits pending TTS/sound cues,
      unsubscribes bus handlers, and unregisters hotkeys.
- [x] Automated pure tests cover JS to Python to shutdown signal path.
- [x] Manual WebView handoff is prepared.

## Verification

- Run `python -m pytest`.
- Prepare exact manual command for real WebView shutdown verification.

## Stop Conditions

- Stop if routing shutdown through `StatusConsoleApi` creates a circular
  dependency with `run()` lifecycle ownership.
- Stop if clean shutdown cannot be reached without ad-hoc callbacks through
  unrelated modules.

## Resolution

**Stale reference note:** this card's "start from `task-ui-09`" instruction
(in the story card) pointed at a file that no longer exists -
`tasks/task-ui-09-status-console-shutdown-control.md` was merged into this
same card and deleted during an earlier "normalize task card names" pass
(commit `5d98b3d`), but the story card's Task Card Sequence line was never
updated to match. Not a blocker (this card's own Summary/Boundary/AC are
already fully self-contained and current) - fixed the stale line in the
story card as part of this task.

**Implementation:**

- `status_console.py`'s `StatusConsoleApi` gained `request_shutdown()` and
  `set_shutdown_event()`, mirroring `set_loop()`'s constructor-optional,
  settable-later pattern. `request_shutdown()` publishes an `INFO`
  `SystemEvent` ("Shutdown requested via Status Console" /
  "Запрошено завершение работы Jarvis") and then sets the given
  `shutdown_event` - it does no teardown itself, so `run_until_shutdown()`
  stays the one clean-shutdown implementation regardless of trigger.
- `main.py`'s `run()` now creates `shutdown_event` before
  `wire_status_console()` and calls
  `live_console.api.set_shutdown_event(shutdown_event)` there, so the
  Status Console button and the `Ctrl+Alt+Q` hotkey both set the identical
  event. No change to `run_until_shutdown()` itself - the existing
  cancel-tasks/await-pending-speech/unsubscribe/unregister-hotkeys path
  (already covered by `test_run_until_shutdown_cancels_tasks_and_
  unsubscribes` and `..._cancels_clipboard_mic_sleep_and_thinking_hotkey_
  listeners`) is reused unchanged.
- Guard: desktop shell adds a `shutdown-zone` (click "Завершить работу" ->
  confirm row, same shape as the existing context-reset confirm);
  touchstrip adds a third actions-page button requiring a 2-second pointer
  hold (`SHUTDOWN_HOLD_MS`, double the existing 1-second reset hold).
  Decision (this card's own "decide" framing): touchstrip gets a shutdown
  action too, deliberately harder to trigger than reset (longer hold, red
  instead of amber on both surfaces - red reserved here for the single most
  severe control on each surface) rather than leaving the two surfaces'
  capabilities to drift apart.
- Verified live via the Preview tools against both `demo.html` (desktop
  confirm-row show/hide) and `touchstrip.html` (actions page, hold
  start/cancel) - no console errors, correct guard behavior (early release
  cancels, no partial shutdown).
- Superseded by the later lifecycle-controller fix: this original task
  shipped with a known limitation where neither this control nor the
  existing hotkey closed the `pywebview` window(s). That is no longer the
  current contract. `main.py` now closes the live Status Console windows
  after the shared clean engine shutdown completes.
- `PROJECT.md` gained an "Architecture v1.2.4" section recording this.

**Automated tests:** `tests/test_status_console.py` gained
`test_request_shutdown_sets_the_given_event_and_publishes_an_info_event`,
`test_set_shutdown_event_wires_up_a_previously_unset_api`, and
`test_request_shutdown_is_a_no_op_without_a_shutdown_event_even_with_a_loop`
(plus `request_shutdown()` added to the existing pre-`set_loop()` no-op
test). `python -m pytest` passes (272 passed).

**Manual WebView handoff (human-run):**

```
python main.py --status-console
```

1. Click "Завершить работу" in the desktop window; confirm the red confirm
   row appears with "Отмена"/"Завершить" - click "Отмена" once and confirm
   the row hides with no effect, then repeat and click "Завершить работу"
   for real.
2. Before the window goes inert, confirm a "Запрошено завершение работы
   Jarvis" entry appeared in the events panel.
3. Confirm the console log shows the same cancel/unsubscribe/unregister
   sequence already produced by `Ctrl+Alt+Q` (mic loop stopped, hotkeys
   unregistered, no further "listening" cue).
4. Confirm the Status Console window closes after teardown completes.
5. Repeat once on the touchstrip window instead: hold "Завершить работу"
   for the full ~2s (fill animation completes) and confirm the same
   teardown; release early on a second run and confirm nothing happens.

Human report pending.
