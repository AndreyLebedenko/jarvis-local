# Task: WARMING runtime state

**Story:** `tasks/story-v1.2.7-activation-and-warmup.md`
**Status:** Backlog.
**Release:** v1.2.7
**Depends on:** `tasks/story-v1.2.7-task-1-ollama-keepalive-warmup.md`
**Detailed card:** `tasks/task-02-status-orb-warming-state.md`

## Summary

Add WARMING as a runtime activation state, visually distinct from listening,
error, and cloud/data-locality indicators.

## Current Boundary

- Follow `tasks/task-02-status-orb-warming-state.md`.
- WARMING is not a privacy state.
- Final timeout calibration waits for measured data.

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
