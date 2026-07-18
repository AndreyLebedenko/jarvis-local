# Story v1.5.1: Stabilization after the journal release

**Status:** Accepted; task cards created (tasks 1-4 below).
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md`
**Release:** v1.5.1 (bugfix/hygiene release; no features)

## User-facing goal

Jarvis shuts down cleanly in every scenario the v1.5.0 release verification
exercised, and the open reports from that verification are either fixed or
explicitly dispositioned. Nothing new to learn for the user; the release
removes error noise and stale defensive code.

## Background

v1.5.0 release verification (2026-07-17/18) left three bug reports and one
older backlog question relevant to console/runtime hygiene:

- `tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md` -
  the only code defect: shutdown can log
  `RuntimeError: cannot schedule new futures after shutdown` from the
  microphone loop's `asyncio.to_thread(stream.read, ...)`.
- `tasks/backlog/status-console-api-stale-pywebview-crash-guard.md` -
  `StatusConsoleApi`'s "log and silently return, never raise" pattern may
  have been unjustified since the v1.2.10 pywebview bridge removal.
- `tasks/bug_reports/2026-07-17-journal-retention-policy.md` - resolved at
  the design level by the near/far consolidation decision (roadmap v1.7.0);
  needs its disposition recorded, not code.
- `tasks/bug_reports/2026-07-17-distorted-voice-in-journal-recording.md` -
  unreproduced capture-time artifact; needs a recurrence protocol, not a
  blind fix.

## Boundaries

- No new features. Journal UX (copy, thumbnails, disk usage, text input)
  is v1.5.2; do not pull it in.
- No capture-path or VAD changes for the unreproduced distortion report -
  a blind filter/AGC change could degrade normal captures (the report's
  own temporary decision stands).
- No automatic journal cleanup of any kind (roadmap cross-cutting rule 8).
- The shutdown fix stays in the audio/shutdown lifecycle; do not redesign
  executor usage project-wide. If a correct fix turns out to require a
  broad executor-lifecycle redesign, that is a stop condition, not scope.

## Task card sequence

1. **task-v1.5.1-1-microphone-shutdown-race** - make microphone shutdown
   await a deterministic read-worker/stream-close boundary before
   background-task cancellation and loop teardown, so no new `to_thread()`
   submission can reach a shutting-down executor. Pure regression test
   with a fake blocking stream and controlled executor proving: (a) no new
   executor job is submitted after the stop boundary; (b) the microphone
   task exits without an ERROR log. Human-run re-check of the exact
   reported scenario.
2. **task-v1.5.1-2-stale-pywebview-guard** - execute the existing backlog
   card: confirm no `webview.create_window(...)` site binds `js_api` to
   `StatusConsoleApi`; then either remove the silent-reject pattern from
   `set_visibility_mode()`/`reset_module()`/`set_reasoning_level()` in
   favor of the transport layer's `ProtocolError` validation, or document
   the real, still-reachable path that justifies keeping it. Update the
   "closed-loop pywebview crash" regression test's framing accordingly.
3. **task-v1.5.1-3-report-dispositions** - docs only. Annotate the
   retention report as design-resolved by the consolidation pipeline
   (pointer to roadmap v1.7.0; report stays open until that pipeline
   ships, but the open question "which policy" is answered). Extend the
   distorted-voice report with a concrete recurrence protocol: on the next
   occurrence, preserve the wav, compare its waveform against a clean
   sibling for clipping/dropouts/resampling artifacts, and check
   correlation with concurrent TTS/sound-cue playback or inference load.
4. **task-v1.5.1-4-microphone-device-matrix** (owner addition,
   2026-07-18) - a human-run quality and stability check matrix across
   microphone device types (USB and Bluetooth at minimum): capture
   quality with preserved evidence wavs, sleep/wake cycles,
   stall/disconnect behavior, clean shutdown, Bluetooth profile-switch
   observations. Agent writes the script and hands over commands; human
   runs it; verified per-device-class facts land in `PROJECT.md`. Runs
   after task 1 so device findings are not confused with the known
   shutdown race. Checks only: any defect found becomes its own bug
   report, not an in-story fix.

## Acceptance criteria

- [x] The reported human scenario (launch with Status Console, change UI
      language, close the console without any request) shuts down with no
      ERROR-level log - human-verified three times on 2026-07-18
      (task-v1.5.1-1 completed).
- [x] A pure test proves the microphone stop boundary: `stop()` stays
      pending until the read worker and loop have finished, and the task
      exits cleanly. The test fails on the pre-fix code. An
      observable-executor test additionally records zero submissions
      after the boundary (supporting evidence, not required to fail
      pre-fix on its own).
- [x] The pywebview guard question is closed (task-v1.5.1-2 completed):
      enum-value silent-rejects removed in favor of transport-layer
      `ProtocolError` validation; the `_schedule()` loop guard kept and
      re-documented with its real remaining justification (GUI-thread
      `on_closed` -> `request_shutdown()`).
- [ ] Both non-code reports carry their dispositions.
- [ ] The microphone device matrix has been run by the human on at least
      one USB and one Bluetooth device, with per-device-class results
      recorded in `PROJECT.md` and any defects filed as bug reports.
- [ ] `python -m pytest`, `python -m ruff check .`, and
      `python -m ruff format --check .` pass.

## Stop conditions

- Stop if the shutdown fix cannot be made deterministic without a broad
  executor-lifecycle or event-loop-ownership redesign - record the design
  problem instead of working around it.
- Stop if a live pywebview `js_api` path into `StatusConsoleApi` is found
  that static inspection cannot rule out - verify with a live check before
  removing the guard (per the backlog card's own stop condition).
- Stop if the distorted-voice artifact reproduces during this story's
  human checks - that changes it from a monitored anomaly into an active
  investigation with preserved evidence, which needs its own task.
