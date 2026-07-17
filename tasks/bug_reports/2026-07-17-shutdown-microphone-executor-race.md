# Microphone shutdown races with the default executor

**Detected at commit:** `3e0484a` (task-journal-07 merged into `main`)
**Detected during:** task-journal-08 release screenshot preparation,
2026-07-17
**Status:** Open; no code change in the current release-wrap-up task.

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

## Future considerations and boundaries

- Make microphone shutdown await a deterministic read-worker/stream-close
  boundary before cancelling or closing the event-loop executor.
- Add a pure test using a fake blocking stream and a controlled executor to
  prove that shutdown never submits a new `to_thread()` job after the stop
  boundary and that the microphone task finishes without an ERROR log.
- Re-run the human scenario: launch, change UI language, close the console
  with no requests, and confirm clean shutdown in both English and Russian.
- Keep the fix in the audio/shutdown lifecycle. Journal persistence,
  language strings, and screenshot capture are not suspected causes.
