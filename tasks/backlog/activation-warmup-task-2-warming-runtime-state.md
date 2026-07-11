# Task: WARMING runtime state

**Story:** `tasks/backlog/activation-warmup.md`
**Status:** Backlog.
**Target:** v1.4.0 or later
**Depends on:** `tasks/backlog/activation-warmup-task-1-ollama-keepalive-warmup.md`

## Summary

Add WARMING as a runtime activation state, visually distinct from listening,
error, and cloud/data-locality indicators.

## Current Boundary

- WARMING is not a privacy state.
- Final timeout calibration waits for measured data.
- User speech during WARMING must be buffered by the VAD/request path, not
  dropped and not submitted before the model is ready.

## Acceptance Criteria

- [ ] WARMING is represented in runtime state.
- [ ] WARMING is visually distinct from LISTENING, IDLE, ERROR, and
      data-locality/cloud indicators.
- [ ] Speech during WARMING is buffered and not dropped.
- [ ] WARMING has an upper wait bound with error transition.
- [ ] Entry/exit/duration are logged as system events.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Prepare visual/manual handoff for real UI timing and color review.

## Stop Conditions

- Stop if WARMING requires larger state-machine redesign than the story allows.
- Stop if buffering conflicts with existing VAD/request boundaries.
- Stop if choosing a safe timeout requires human timing data that has not been
  collected yet.
