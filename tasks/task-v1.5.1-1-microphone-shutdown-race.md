# Task v1.5.1-1: Microphone shutdown executor race

**Status:** Ready.
**Story:** `tasks/story-v1.5.1-stabilization.md`
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

- After the stop boundary completes, the microphone code submits no new
  executor job (`to_thread` or equivalent). "Completes" must be awaitable
  by `run_until_shutdown()` before it cancels tasks.
- The microphone task then exits cleanly (no exception besides
  `CancelledError` swallowed by cancellation, no ERROR log from the
  shutdown gather).
- A stream `read()` still blocked in a worker thread at teardown must not
  produce an ERROR-level log or unhandled exception, regardless of when
  the thread finally returns.

## Acceptance criteria

- [ ] A pure test with a fake blocking stream and a controlled/observable
      executor seam proves no new executor submission happens after the
      stop boundary. The test fails against the pre-fix code.
- [ ] A pure test proves the microphone task finishes without an ERROR
      log when stop and cancellation race a blocked read.
- [ ] Existing microphone tests (sleep/wake, buffer invalidation, MME
      fresh-stream recovery) still pass unchanged.
- [ ] Human-run re-check of the reported scenario passes with no
      ERROR-level shutdown log, in both English and Russian UI languages.
      Agent hands over the exact steps; human reports output.
- [ ] `python -m pytest`, `python -m ruff check .`,
      `python -m ruff format --check .` green.

## Stop conditions

- Stop if a deterministic boundary requires a broad executor-lifecycle or
  event-loop-ownership redesign (per the story card).
- Stop if the fix would change capture semantics (dropped audio outside
  shutdown, altered pause behavior) - that trade-off needs the human.
