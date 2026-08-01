# Task v1.8.0-25: Consolidation executor and control

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-24.

## Summary

Execute explicit consolidation plans with restart recovery, API control, and
projection consistency.

## Current boundary

In scope: plan execution, recovery markers, local API, Journal UI control,
projection refresh, usage reporting, and tests.

Out of scope: background scheduling, changing planning policy, semantic
backend selection, and automatic deletion without user command.

## Requirements

- Execute only a previously calculated explicit plan.
- Protect active sessions.
- Use recoverable steps for file and database changes.
- Refresh derived projections after execution.
- Surface partial failure and recovery state honestly.
- Provide authenticated local controls and Hidden-mode suppression.
- Preserve raw textual history and provenance.

## Acceptance criteria

- [ ] Execution is explicit and auditable.
- [ ] Crash/restart recovery is tested.
- [ ] Projection data remains consistent after execution.
- [ ] Active-session guard cannot be bypassed.
- [ ] UI/API report progress and failure states.

## Stop conditions

- Stop if file/database mutation cannot be made recoverable.
- Stop if execution can invalidate retrieval provenance.
- Stop if hidden/background behavior could surprise the user.

## Verification

- Executor, recovery, API, UI, and projection tests.
- `python -m pytest`
- Ruff checks.
