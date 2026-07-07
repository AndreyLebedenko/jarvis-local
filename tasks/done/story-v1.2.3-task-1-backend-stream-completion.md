# Task: Backend stream completion reliability

**Story:** `tasks/story-v1.2.3-hygiene-and-known-debts.md`
**Status:** Completed.
**Release:** v1.2.3

## Summary

Prevent Jarvis from remaining busy forever if an Ollama stream ends without a
final `done: true` chunk.

## Current Boundary

- Write the failing regression test first.
- Fix only the confirmed backend-stream completion edge case.
- Do not add a broad turn watchdog unless this narrow fix is insufficient.

## Acceptance Criteria

- [x] A pure automated regression test covers a stream ending without
      `done: true`.
- [x] The orchestrator clears busy for that edge case.
- [x] Error or warning feedback is visible through existing logging/cue paths
      where appropriate.
- [x] Normal successful `done: true` completion behavior is unchanged.
- [x] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if the edge case cannot be reproduced with a focused pure test.
- Stop if the fix requires broad orchestration redesign.
- Stop if failures are infrastructure-related rather than code-related.

## Resolution

Root cause: `OllamaBackend.chat()` (`backend.py`) only published
`ResponseComplete` from inside the `if chunk.get("done")` branch. If the
stream body ended (connection closed / iteration exhausted) without ever
sending a `done: true` chunk, `ResponseComplete` was never published.
`Orchestrator.finish_turn()` - the only place that clears `_busy` - runs
exclusively off the back of that event (`main.py`'s
`_on_full_response_complete`), so this stream shape left `_busy` `True`
forever; every later utterance/clipboard turn would be silently ignored as
"previous request still in flight". No broad turn watchdog was needed - the
existing `finally: finish_turn()` wiring in `main.py` was already correct,
the gap was purely that the completion event was never emitted.

Fix: `chat()` now tracks whether a `done` chunk was ever seen. If the
stream ends without one, it logs a warning
("Ollama stream ended without a done:true chunk") and publishes
`ResponseComplete` anyway, with zeroed `LatencyMetrics` (real metrics are
unavailable in this case, so zeros are published rather than invented
numbers). Two new regression tests in `tests/test_backend.py` cover this:
one asserting `ResponseComplete` is still published, one asserting tokens
already seen before the stream cut off are still republished as
`ResponseToken`s. Both fail without the fix and pass with it. Existing
`done: true` tests are unchanged and still pass.
