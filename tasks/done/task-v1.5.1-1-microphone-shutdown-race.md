# Task v1.5.1-1: Microphone shutdown executor race

**Status:** Completed.
**Story:** `tasks/done/story-v1.5.1-stabilization.md`
**Source report:**
`tasks/bug_reports/2026-07-17-shutdown-microphone-executor-race.md`

## Summary

Make microphone shutdown deterministic: after `AudioInput.stop()` returns
(or after an explicit new stop boundary completes), the microphone loop
must be guaranteed to submit no further executor jobs, so background-task
cancellation and event-loop/executor teardown can never race a blocking
`stream.read()` into `RuntimeError: cannot schedule new futures after
shutdown`.

## Context you need

- The report above: exact symptom, trace, and the human repro scenario
  (launch with Status Console, change UI language, close the console
  window without sending any request).
- `src/jarvis/audio/input.py`:
  - `AudioInput.stop()` (line ~201) sets `_stop_requested`, wakes the
    sleep wait, and stops the active stream - but does not wait for the
    loop to actually pass its last `to_thread()` call.
  - `_read_stream_block()` (line ~207) is the `asyncio.to_thread(
    stream.read, ...)` site the trace points to.
  - `run_microphone_loop()` (line ~242) owns the stream context and the
    fresh-stream-per-resume behavior (MME wake recovery) - preserve both.
- `src/jarvis/app.py` `run_until_shutdown()` (line ~703): calls
  `await app.audio_input.stop()`, then cancels all background tasks and
  gathers them. The mic loop task is one of them.
- Existing regression-test style for this module: tests drive
  `run_microphone_loop()` with fake streams via the `stream_factory`
  seam (see `tests/` microphone tests and `InputStreamLike`).

## Boundary

- Changes limited to `src/jarvis/audio/input.py`, minimal adjustments in
  `src/jarvis/app.py`'s shutdown sequence if the new boundary needs an
  await point there, and tests.
- Preserve every existing capture contract: buffer invalidation on
  pause/sleep, fresh stream per resume, pause-spanning read discard,
  cooperative stop interrupting a blocked read.
- Do not redesign executor usage project-wide and do not introduce a
  custom executor unless the deterministic boundary is impossible without
  one - that is a stop condition, not an implementation choice.

## Requirements

(Revised 2026-07-18 after review: the original text asked the
observable-executor test itself to fail pre-fix, which is impossible -
the pre-fix loop also checks its flags before every submission, so the
defect is not an engine-internal post-stop submission but stop()
returning while the loop and its read worker are still alive, combined
with the process-lifecycle race around `webview.start()`.)

- **Terminal microphone stop.** `AudioInput.stop()` sets the stop flag,
  stops the active stream, and then unconditionally waits until
  `run_microphone_loop()` has actually exited. No timeout: a bounded
  degraded-shutdown mode for a driver whose read never returns would be a
  separate, explicit architectural decision, not a WARN-and-continue path
  inside this guarantee.
- **No stop-before-start race.** stop() is terminal: a microphone loop
  that starts (or resumes scheduling) after stop() must exit immediately
  without opening a stream or submitting any executor job. The loop must
  not reset the stop flag on entry.
- **Engine lifetime ownership.** `run_with_status_console()` completes a
  `concurrent.futures.Future` from the engine callback (result or
  exception) and blocks on it after `webview.start()` returns - no
  thread-list handoff (racy if the callback has not run yet), no join
  timeout, and an engine exception propagates to the caller instead of
  dying silently in the thread.
- The microphone task exits cleanly: no exception into the shutdown
  gather, no ERROR log.

## Acceptance criteria

- [x] A pure test proves the regression property: with a controlled read
      worker still blocked, `stop()` remains pending; after the worker is
      released the loop finishes first and only then does `stop()`
      complete. Fails against the pre-fix code (verified: 4 regression
      tests fail on `a2a154e` in 1.95 s).
- [x] An additional pure test with an observable executor seam records
      that no new submission happens after `stop()` returns (supporting
      evidence; not required to fail pre-fix on its own).
- [x] A pure test proves stop-before-start: after `stop()`, a late-
      starting loop exits without ever opening a stream.
- [x] A pure test proves `run_until_shutdown()` with a real microphone
      loop completes without any exception result or ERROR log.
- [x] A pure test proves `run_with_status_console()` does not return
      before the engine callback has completed, even if `webview.start()`
      returns before the callback has started running.
- [x] A pure test proves an exception raised by the engine callback
      propagates to `run_with_status_console()`'s caller.
- [x] Existing microphone tests (sleep/wake, buffer invalidation, MME
      fresh-stream recovery) still pass unchanged.
- [x] Human-run re-check of the reported scenario: executed three times
      on 2026-07-18, all clean (no ERROR-level shutdown log).
- [x] `python -m pytest` (969 passed, 1 skipped), `python -m ruff
      check .`, `python -m ruff format --check .` green.

## Implementation notes (2026-07-18)

- Root cause was process-lifecycle, not engine-internal: pywebview 6.2.1's
  `start()` never joins its func thread, so interpreter shutdown raced the
  engine teardown. See the bug report for the full analysis.
- Two pre-existing tests faked `webview.start` without ever running the
  callback; under the engine-completion-future contract that is a fake
  violating real pywebview behavior (it always runs func) and deadlocked
  the suite. Both fakes now run the callback with `run` monkeypatched.
- The pending-stop regression test releases its parked read worker in a
  `finally`, so a failing run reports instead of hanging pytest's
  executor teardown.

## Stop conditions

- Stop if a deterministic boundary requires a broad executor-lifecycle or
  event-loop-ownership redesign (per the story card).
- Stop if the fix would change capture semantics (dropped audio outside
  shutdown, altered pause behavior) - that trade-off needs the human.
