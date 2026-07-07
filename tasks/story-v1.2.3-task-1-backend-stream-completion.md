# Task: Backend stream completion reliability

**Story:** `tasks/story-v1.2.3-hygiene-and-known-debts.md`
**Status:** Backlog.
**Release:** v1.2.3

## Summary

Prevent Jarvis from remaining busy forever if an Ollama stream ends without a
final `done: true` chunk.

## Current Boundary

- Write the failing regression test first.
- Fix only the confirmed backend-stream completion edge case.
- Do not add a broad turn watchdog unless this narrow fix is insufficient.

## Acceptance Criteria

- [ ] A pure automated regression test covers a stream ending without
      `done: true`.
- [ ] The orchestrator clears busy for that edge case.
- [ ] Error or warning feedback is visible through existing logging/cue paths
      where appropriate.
- [ ] Normal successful `done: true` completion behavior is unchanged.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if the edge case cannot be reproduced with a focused pure test.
- Stop if the fix requires broad orchestration redesign.
- Stop if failures are infrastructure-related rather than code-related.
