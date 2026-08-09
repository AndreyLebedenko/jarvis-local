# Task v1.8.0-24: Historical consolidation planner

**Status:** Completed 2026-08-08. Scope decided with the owner before
implementation: audio media action is binary KEEP/REMOVE only (no
compression/bitrate-reduction action in this card), and images/screenshots
are out of scope for this planner (untouched, not part of the plan).
Implemented and verified by `python -m pytest` (1896 passed, 1 skipped) and
ruff; see the consolidation planner contract in `PROJECT.md`.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-18 through v1.8.0-23.

## Summary

Calculate safe near/far consolidation plans without performing media or data
mutation.

## Current boundary

In scope: planning rules, active-session exclusion, transcript prerequisites,
media retention/reduction candidates, derived-layer impact, and tests.

Out of scope: executing plans, background scheduling, UI controls, and
automatic deletion.

## Requirements

- Never plan consolidation for the active session.
- Require successful transcript availability before audio reduction/removal
  is planned.
- Preserve full textual history, transcripts, annotations, and provenance.
- Identify derived projection updates required after execution.
- Produce auditable dry-run output.
- Keep all decisions explicit; no background consolidation.

## Acceptance criteria

- [x] Plans are deterministic for fixed session state.
- [x] Active session is excluded.
- [x] Audio is not planned for removal without transcript coverage.
- [x] Raw text, transcript, annotation, and retrieval impact is visible.
- [x] No files or databases are mutated by planning.

## Stop conditions

- Stop if a safe plan requires guessing transcript completeness.
- Stop if media reduction would break replayability without owner-approved
  policy.

## Verification

- Focused planner tests.
- `python -m pytest`
- Ruff checks.
