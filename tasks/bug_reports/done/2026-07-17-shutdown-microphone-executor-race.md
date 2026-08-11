# Microphone shutdown races with the default executor

**Detected at commit:** `3e0484a` (task-journal-07 merged into `main`)
**Detected during:** task-journal-08 release screenshot preparation,
2026-07-17
**Status:** Fixed and verified (task-v1.5.1-1, 2026-07-18). The human
re-ran the reported scenario three times; all three shutdowns completed
without errors.

## Symptoms

Starting Jarvis with the Status Console, changing the UI language, and
closing the console window without sending a request produced an ERROR during
shutdown:

```text
Shutdown: background task Task-55 raised instead of exiting cleanly
RuntimeError: cannot schedule new futures after shutdown
```

The trace points to `AudioInput.run_microphone_loop()` awaiting
`asyncio.to_thread(stream.read, block_samples)`. The remaining shutdown steps
complete and the process exits, but the shutdown is not clean and emits a
false-looking task failure.

## Suspected current cause

`run_until_shutdown()` calls `AudioInput.stop()` and then immediately cancels
all background tasks. `AudioInput.stop()` stops the active stream, but a
`stream.read()` already running in the default executor is not cancellable by
the asyncio task cancellation. The read can race with task cancellation and
executor teardown; a subsequent `to_thread()` submission then reaches an
executor that is already shutting down.

The UI language change is incidental. It persists the new UI setting before
the close request, but the failing path is microphone shutdown and does not
depend on the selected language or on a model request.

## Temporary decision

No code change in task-journal-08. The issue is outside the documentation and
release-wrap-up boundary and requires an explicit shutdown design for the
blocking microphone read. This report preserves the exact failure instead of
silencing the exception or broadly changing executor lifecycle during release
preparation.

## Root cause (verified 2026-07-18, task-v1.5.1-1)

The race is not internal to the engine loop: the microphone loop checks
its stop/awake flags before every `to_thread()` submission, so engine-side
ordering alone cannot submit after `stop()`. The executor teardown comes
from the other side of the process. pywebview 6.2.1's `webview.start(func)`
runs `func` (our `start_jarvis`, which owns `asyncio.run(...)` and the
whole engine) in a plain `threading.Thread` and returns without joining it
the moment the GUI loop exits - verified by reading the installed
package's `webview/__init__.py`. Closing the console window therefore made
`main()` return and interpreter shutdown begin (concurrent.futures'
atexit hook forbids new submissions) while the engine thread was still
running its clean shutdown sequence; the microphone loop's next
`stream.read` submission then raised, unwound through
`run_microphone_loop()`, and the shutdown gather logged it as a task
failure.

## Fix (task-v1.5.1-1, revised in review)

- **Engine lifetime ownership.** `run_with_status_console()` creates a
  `concurrent.futures.Future` before `webview.start()`; the engine
  callback completes it with the engine's result or exception, and the
  main thread blocks on `result()` after `webview.start()` returns. The
  interpreter no longer races the engine teardown - including the case
  where `webview.start()` returns before the callback thread was even
  scheduled - and an engine exception propagates to the caller instead of
  dying silently in pywebview's unjoined thread. No join timeout: a hung
  engine is an honest hang to diagnose, not a silent resumption of the
  race. This is the root-cause fix.
- **Terminal microphone stop.** `AudioInput.stop()` now waits
  unconditionally until `run_microphone_loop()` (and its blocking read
  worker) has actually exited, so once `run_until_shutdown()` moves on to
  cancelling tasks, the microphone code can no longer submit any executor
  job. The loop no longer resets the stop flag on entry, closing the
  stop-before-start race: a loop started after `stop()` exits immediately
  without opening a stream. There is deliberately no timeout (see
  `PROJECT.md`'s audio_in entry for the recorded boundary on stalled
  drivers).
- Regression tests confirmed to fail on the pre-fix code:
  `test_stop_stays_pending_until_the_read_worker_and_loop_have_finished`,
  `test_stop_is_terminal_a_late_starting_loop_never_opens_a_stream`,
  `test_run_with_status_console_waits_for_a_delayed_engine_callback`,
  `test_run_with_status_console_reraises_an_engine_callback_failure`.
  Supporting (not required to fail pre-fix):
  `test_no_executor_submission_happens_after_stop_has_returned`
  (observable default executor records zero submissions after the
  boundary),
  `test_run_until_shutdown_with_a_real_microphone_loop_exits_cleanly`.

## Verification

- Human-run scenario (launch, change UI language, close the console with
  no requests) executed three times on 2026-07-18: no ERROR output, clean
  `Shutdown: teardown complete` each time.
