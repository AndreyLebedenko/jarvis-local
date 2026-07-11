# Task: Orb click activation trigger

**Story:** `tasks/backlog/activation-warmup.md`
**Status:** Backlog.
**Target:** v1.4.0 or later
**Depends on:** `tasks/backlog/activation-warmup-task-2-warming-runtime-state.md`

## Summary

Add status-orb click as a universal fallback activation trigger using the same
activation path as push-to-talk.

## Current Boundary

- No OS-level hotkey work.
- No wake word work.
- The orb click must call the same activation entry point as push-to-talk, not
  duplicate activation/warmup logic.

## Acceptance Criteria

- [ ] Clicking the orb in IDLE triggers activation/warmup.
- [ ] Repeated clicks during WARMING or LISTENING do not duplicate warmup
      requests.
- [ ] Orb click and PTT share one activation entry point.
- [ ] Tests cover DOM/API behavior without real WebView hardware.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if orb click cannot share the same activation path as PTT.
- Stop if UI state would show activation that the engine has not accepted.
