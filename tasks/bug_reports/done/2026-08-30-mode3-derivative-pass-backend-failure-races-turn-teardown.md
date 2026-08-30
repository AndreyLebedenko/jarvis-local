# Mode 3 derivative-pass backend failure can pre-clear busy before the turn actually finishes tearing down

**Detected on:** branch `task-v1.9.0-3-mode3-second-pass-and-tts-suppression`,
uncommitted at the time of writing (parent commit `28fde3c` on `main`).
**Status:** Fixed and verified (task-v1.9.0-3, 2026-08-30). Independently
resurfaced by a structured `/code-review high` pass as a PLAUSIBLE finding;
fixed within the same task rather than deferred, per explicit owner
direction. `_dispatch_backend_request()`'s except-Exception branch now
gates `self._busy = False` on the same `claim_turn_end()` check that already
guarded `record_aborted_turn()`, so a losing claim (this dispatch running as
a sub-pass of a turn `_on_full_response_complete()` still owns) leaves busy
alone for that owner's own `finish_turn()` to clear. Verified by a red-then-
green regression test
(`test_derivative_pass_backend_failure_does_not_clear_busy_early` in
`tests/test_main.py`) reproducing a real (non-cancellation) exception on the
derivative dispatch after the turn's one claim was already taken; full
`python -m pytest` suite and `ruff` gates green.

## Symptoms visible to the user

In response mode 3 (Text+TTS), if the backend call for the *second*
(derivative) pass fails outright (a real exception - not an interrupt, not
a network timeout that resolves, an actual raised error), the user may:

- Hear the "error" sound cue followed shortly after by the normal
  "listening" cue, back to back, for what looks like one turn - confusing,
  though not a crash.
- In a narrow timing window, be able to start a *new* turn (voice or text)
  before the mode-3 turn has actually finished tearing down (its
  `TurnCompleted` has not been published yet), because `_busy` was cleared
  early by the failure path below.

The journal record itself is unaffected: the canonical text is recorded
correctly, and the derivative field is written as whatever partial text (or
empty string) streamed before the failure - no crash, no lost data,
no malformed journal entry.

## Suspected current cause

`Orchestrator._dispatch_backend_request()` (app.py) has an
`except Exception:` branch that treats *any* failure of the backend call it
wraps as "this turn is over": it plays the "error" cue, and unconditionally
sets `self._busy = False`, regardless of whether `claim_turn_end()`
succeeds. That is correct for a normal (single-pass) turn, where this
method is called directly from `_start_turn()` and a failure here really is
the whole turn's only outcome.

Mode 3's `run_derivative_pass()` (added in this task) calls the same
`_dispatch_backend_request()` a *second* time, from deep inside
`_on_full_response_complete()` (itself still holding the turn's one
`claim_turn_end()` claim from pass 1). If this second call's backend
request throws:

1. `_dispatch_backend_request()`'s except-Exception branch catches it,
   plays "error", and sets `self._busy = False` immediately - but does
   *not* re-raise, and does not call `record_aborted_turn()` (its own
   `claim_turn_end()` check fails, since pass 1's `_on_full_response_
   complete()` call already claimed the turn at its own entry).
2. `run_derivative_pass()` sees no exception, proceeds normally: computes
   `derivative_text` from whatever partial tokens streamed, and calls
   `record_assistant(canonical_text, spoken_derivative=derivative_text)`.
3. `_on_full_response_complete()` (still running) continues to
   `wait_for_pending()` + its own `finally` (`finish_turn()` +
   `TurnCompleted` + "listening" cue) as if pass 2 had completed
   normally.

The two "this turn is over" tail sequences (the swallowed one inside
`_dispatch_backend_request`, and the real one in `_on_full_response_
complete()`'s `finally`) both run, back to back, and `_busy` is visible as
`False` for the stretch between step 1 and the `finally` block's own
(redundant) `finish_turn()` call - during which a concurrent new-turn
request would read `is_busy() == False` and be accepted.

## Temporary decision

Left as-is for this task card. Reasons this was not fixed here:

- The failure mode is a real backend exception specifically on the
  *second* (reasoning-off, short) dispatch of an already-successful mode-3
  turn - narrow in practice, and degrades to a confusing double-cue plus a
  small race window, not data loss or a crash.
- A correct fix touches `_dispatch_backend_request()`'s shared
  failure-handling branch, which is also the normal (single-pass) turn's
  own failure path and is one of the most heavily reviewed, race-sensitive
  pieces of this file (see its own "task-v1.7.0-3 review, Nth round"
  comments). Changing its claim/busy semantics to distinguish "a pass that
  is not the whole turn failed" from "the turn failed" is exactly the kind
  of change CLAUDE.md's stop conditions (0.3/0.4) call out - non-obvious
  trade-offs with architectural consequences - and deserves its own
  reviewed task, not a bolt-on inside this one.
- The task card's own acceptance criteria and verification scope are about
  the *success* path (mute the first pass, speak the derivative, persist
  it) plus the two named stop conditions (both about pipeline shape, not
  backend-failure semantics); backend-failure handling for the derivative
  pass specifically was never part of this slice's boundary.

## Future considerations

- A real fix likely needs `_dispatch_backend_request()` (or a thin wrapper
  around it for non-primary passes) to know whether it is "the whole turn"
  or "a sub-pass of an already-owned turn", and skip its own busy-clear/
  cue-play/`claim_turn_end()` check when it is not - leaving that entirely
  to the caller (`run_derivative_pass()`/`_on_full_response_complete()`).
- Alternatively, `run_derivative_pass()` could catch the *specific*
  `BackendRequestFailed`-shaped failure itself (e.g. by not delegating to
  `_dispatch_backend_request()` for this one call, or by having a
  `pass_kind` parameter change its internal exception handling) - but that
  duplicates dispatch logic rather than sharing it, so it needs its own
  design discussion, not a quick patch.
- Worth a live check once mode 3 is in regular use: whether backend
  failures on the derivative pass are common enough in practice
  (short, reasoning-off calls are usually fast and reliable) to justify
  prioritizing this over other backlog items.
