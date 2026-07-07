# Task: Control plane manual verification handoff

**Story:** `tasks/story-v1.2.4-status-console-control-plane.md`
**Status:** Completed (handoff prepared; awaiting human verification report).
**Release:** v1.2.4
**Depends on:** `tasks/done/story-v1.2.4-task-3-config-menu-iteration-1.md`

## Summary

Prepare and document the human-run verification for real WebView shutdown and
real model/microphone source behavior.

## Current Boundary

- Handoff script or instructions only.
- The agent does not run WebView, live Ollama, or real audio-device checks.
- Do not close the story until the human reports results.

## Acceptance Criteria

- [x] Handoff gives exact command to launch the live Status Console.
- [x] Handoff explains how to verify guarded shutdown.
- [x] Handoff explains how to verify model dropdown behavior.
- [x] Handoff explains how to verify microphone dropdown behavior.
- [x] Handoff explains expected behavior when local Ollama or audio devices are
      unavailable.
- [x] Automated pure checks still pass before handoff.

## Verification

- Run `python -m pytest`.
- Human runs the documented manual checks and reports output.

## Stop Conditions

- Stop if manual verification reveals a behavior outside the story boundary.
- Stop if live checks fail due to environment/tooling issues outside the task.

## Resolution

Consolidates the two handoffs already written per-task
(`tasks/done/story-v1.2.4-task-1-shutdown-control.md` and
`tasks/done/story-v1.2.4-task-3-config-menu-iteration-1.md`) into one
walkthrough covering a single real session, instead of two separate
launches. `python -m pytest` confirmed passing before writing this
(300 passed) - see those two cards' own Resolution sections for what each
one added.

Real shutdown/config-menu behavior only exists behind `main.py`'s real
`run()` - `manual_check_status_console.py` is a separate, already-existing
demo/QA harness (fake bus, no `shutdown_event`, no real config write) for
visual/state-cycling checks only (task-ui-02 through task-ui-06) and is
**not** the target of this handoff; clicking Shutdown there is a guarded
no-op by design (no `shutdown_event` ever wired into that harness).

**Update (2026-07-07): first real human run of step 1 found and fixed a
genuine bug**, doing exactly what this handoff was for. The first
Shutdown click worked correctly (silent, clean teardown, window left
open but inert as documented) - but looked like nothing had happened, so
a confused second click hit `StatusConsoleApi`'s now-closed `asyncio`
loop and crashed pywebview's JS-API dispatch thread with `RuntimeError:
Event loop is closed`. Fixed: every `StatusConsoleApi` method now treats
an already-closed loop as a safe no-op (`_loop_is_usable()`), and the
Shutdown button disables itself immediately on click as a cosmetic
guard against the confusing repeat click in the first place. Full
write-up in `PROJECT.md`'s Architecture v1.2.4 section. Regression test:
`tests/test_status_console.py::
test_api_methods_are_a_safe_no_op_after_the_loop_has_closed`. Step 1
below is otherwise unchanged - the human should now see the button go
disabled right after clicking "Завершить", and a second click (if
attempted) should now be silently ignored rather than crash.

### Manual handoff (human-run)

**Command:**

```
python main.py --status-console
```

(Add `--no-touchstrip` to skip the touchstrip window if not needed for
this pass.)

**1. Guarded shutdown - desktop.**
Click "Завершить работу" in the desktop window. Confirm the red confirm
row appears with "Отмена"/"Завершить". Click "Отмена" once - confirm the
row hides and nothing else happens. Repeat and click "Завершить" for
real. Before the window goes inert, confirm a "Запрошено завершение
работы Jarvis" entry appeared in the events panel. Confirm the console
log shows the same cancel/unsubscribe/unregister sequence the
`Ctrl+Alt+Q` hotkey already produces (mic loop stopped, hotkeys
unregistered, no further "listening" cue). Confirm the window itself
stays open but inert afterward - this is expected (see PROJECT.md's
Architecture v1.2.4 section and README's Known Issues: neither the
hotkey nor this control closes the `pywebview` window, since its native
GUI loop is independent of the `asyncio` loop that just tore down) -
close it manually.

**2. Guarded shutdown - touchstrip.**
On a fresh run, hold "Завершить работу" on the touchstrip's actions page
for the full ~2 s (fill animation completes) and confirm the same
teardown as above. On another fresh run, release early and confirm
nothing happens (no partial shutdown).

**3. Model dropdown - normal case.**
With local Ollama running, click "⚙ Настройки" to open the config menu.
Confirm the Model dropdown populates from a real `GET /api/tags` (cross-
check against `ollama list`) and defaults to the currently configured
model (`config.toml`'s `backend.model`, or the built-in default).

**4. Model dropdown - degraded case.**
Stop the local Ollama service (or otherwise make port 11434
unreachable), then reopen the config menu (closing and reopening
re-fetches - see `toggleConfigMenu()`). Confirm the Model dropdown
degrades to just the current configured value (no crash, no empty
dropdown, no hang) and a WARN system event appears
("Не удалось получить список моделей Ollama..."). Restart Ollama
afterward and confirm reopening the menu again repopulates normally.

**5. Microphone dropdown - normal case.**
Confirm the Microphone dropdown populates from real input-capable
devices (cross-check against Windows Sound settings' input list, or
`python -c "import sounddevice; print(sounddevice.query_devices())"`),
including a "(системный микрофон по умолчанию)" option for the empty-
string default. Confirm it defaults to the currently configured device.

**6. Microphone dropdown - degraded case.**
If a way to simulate audio-subsystem failure is available (e.g.
disabling all input devices in Windows, or unplugging the only USB
microphone if that is the sole input device), reopen the config menu and
confirm the same graceful degrade as step 4 (current value only, WARN
event, no crash).

**7. Save and restart-to-apply.**
Change the Model and/or Microphone selection and click "Применить".
Confirm the amber "Изменения сохранены - перезапустите Jarvis, чтобы
применить" banner appears immediately. Confirm `config.ui.toml` now
exists in the repository root with exactly those two values, and that
`config.toml` (if present) is unchanged.

**8. Restart-to-apply actually applies.**
Restart Jarvis (`python main.py --status-console` again). Confirm the
pushed model label matches the saved model, and confirm the newly
selected microphone device is the one actually captured from (speak into
the new device specifically if more than one is available and compare
against speaking into a different, non-selected device).

Human report pending - do not close this story until reported.
