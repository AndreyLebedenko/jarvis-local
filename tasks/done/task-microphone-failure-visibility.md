# Task: A microphone that cannot capture says so

**Status:** Completed. Owner-run hardware verification 2026-07-25, and
both branches also appear in one live log: a real capture failure on an
unsupported sample rate reported through chip, panel, and log, and normal
sleep/wake stayed quiet after a restart on a working device.
**Story:** `tasks/done/story-microphone-device-identity.md`
**Depends on:** `tasks/done/task-microphone-device-identity.md`, which gives the
resolution failure a typed shape to report.

## Summary

`run_microphone_loop()` raises into a background task whose exception is
observed only during shutdown teardown, and `ModuleHealthTracker` moves
the microphone chip only on `MicSleepToggled`. A capture loop that never
started therefore reads as "listening" for the whole session. Make the
failure visible at the moment it happens.

## Context you need

- `src/jarvis/app.py:1153`: the loop is one of the background tasks; a
  raise there is not observed until `run_until_shutdown()` tears down.
- `src/jarvis/ui/module_health.py:94`, `_on_mic_sleep_toggled()`: the only
  signal that moves the microphone chip. Every other module already has a
  failure signal - `CaptureFailed`, `TtsEngineLoadFailed`,
  `CameraCaptureFailed` - and the microphone is the gap.
- `src/jarvis/core/system_log.py`, `publish_system_event()`: the one call
  that writes both the English system-log line and the localized
  events-panel entry.
- `src/jarvis/ui/status_console_ui/strings.js`: `en` and `ru` key sets
  must stay identical; `tests/test_ui_i18n.py` asserts it.

## Boundary

- Reporting only. No retry, no reopening, no hotplug recovery: a failed
  microphone reports and stays reported until restart. Recovery is a
  design of its own and inventing one here would hide exactly the signal
  this card exists to produce.
- The loop must not take the process down. Jarvis stays usable through
  the Journal's text input, which is how the LAN camera checklist was
  verified while this bug was open.

## Requirements

- A failure to open or read the capture stream publishes a typed event
  carrying a short reason, and exits the loop cleanly.
- `ModuleHealthTracker` turns that event into `HealthStatus.ERROR` on
  `ModuleId.MICROPHONE` with its own detail key.
- One `publish_system_event()` call at ERROR level from source `STT`, so
  the events panel gets a localized entry and the system log gets the
  English line. The message names the failure and, for an ambiguous
  device, its candidates - the log may carry the candidate list; the
  panel entry stays a device-selection failure without payload detail.
- The existing quiet paths stay quiet: a read interrupted by stop(),
  sleep, or buffer invalidation is not a failure and must not report one.
- Automated tests, all pure: a stream factory that raises publishes the
  event, transitions the chip, and lets the loop exit; a stop-requested
  read failure publishes nothing; the health tracker maps the event to
  ERROR; both string catalogs carry the new keys.

## Acceptance criteria

- [x] With an unresolvable microphone configured, the console shows a
      microphone chip in error, an events-panel entry, and a
      `logs/jarvis.log` line, within a second of startup. Verified
      2026-07-25 on a device that answered with
      `PortAudioError('Error opening InputStream: Invalid sample rate')` -
      a failure mode nobody had predicted, reported correctly anyway.
- [x] Jarvis keeps running and text turns still work.
- [x] Normal sleep/wake produces no failure report: after a restart on a
      working device the same session logged plain `Microphone asleep` /
      `Microphone awake` and captured four turns.
- [x] `python -m pytest` and Ruff are green.

## Outcome

`MicrophoneCaptureFailed(reason)` is published by
`run_microphone_loop()`'s own `except Exception`, which also logs with a
traceback; `ModuleHealthTracker` maps it to ERROR with
`mic_detail_capture_failed`, and `_on_microphone_capture_failed()` in
`app.py` publishes the single ERROR system event from source `STT`.
Cancellation passes through untouched because `CancelledError` is a
`BaseException`, and the existing quiet returns for stop/sleep/buffer
invalidation are covered by their own tests so a clean shutdown stays
silent.

**Review finding (P1, 2026-07-25), fixed here.** The first implementation
let a plain sleep/wake toggle repaint the chip back to "listening" after
the capture loop had died, because `_on_mic_sleep_toggled()` did not know
the loop was gone. `ModuleHealthTracker` now latches the failure and
ignores later `MicSleepToggled` signals for the microphone;
`test_sleep_wake_after_a_capture_failure_never_says_listening_again()`
pins it. The same review caught PROJECT.md claiming sleep/wake restarts
the loop - it does not, and the entry was corrected with the code.

**The sleep toggle's own feedback, settled 2026-07-25 (owner decision,
after the question was answered by test rather than by argument).** The
open question was whether muting a dead microphone could ever matter -
that is, whether a microphone can become available again while muted, and
in what state. Four tests in `tests/test_audio_in.py` answer it: a failed
loop never re-enters the stream factory on wake; a session that starts
muted defers the failure until the first wake; the toggle keeps flipping
`is_awake` with nothing capturing; and no sleep state is persisted, so
the only recovery - a restart - always comes back awake. There is no
"muted but available again" state, so the toggle after a failure has
nothing to preserve and no effect worth announcing.

Implemented accordingly: `AudioInput.capture_failed` latches the failure,
and `_on_mic_sleep_toggled()` answers the keypress with the
stopped-microphone notice (WARN, source `HOTKEY`, its own catalog key in
both languages) plus the sleep cue in both directions. WARN rather than
ERROR because the failure was already reported once when it happened.

Startup order matters and holds: `wire_status_console()` seeds the
microphone chip from `is_awake` before the capture task is created, so a
failure can only arrive after the seed, never be overwritten by it. If
that order ever changes, the seed needs to consult capture state - worth
knowing before moving either call.
