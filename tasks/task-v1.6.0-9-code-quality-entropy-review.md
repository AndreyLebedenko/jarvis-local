# Task v1.6.0-9: Code quality entropy review

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-1 through task-v1.6.0-8 completed and reviewed.

## Summary

Review the completed attachment implementation for code entropy introduced
across planning, normalization, orchestration, transport, journal recording,
and Journal UI layers. Fix real duplicated contracts before release
verification starts.

## Context you need

- `PROJECT.md` section "Code entropy review practice (maintenance)".
- `tasks/done/story-code-entropy-reduction.md`: what counts as entropy and
  what does not.
- All completed v1.6.0 implementation task cards and their diffs.
- Likely attachment seams to compare side by side:
  - text/image/audio attachment validation and result shaping;
  - Python planner output vs transport response payloads;
  - backend media construction vs orchestration media handling;
  - journal media/event representation vs UI attachment rendering;
  - JS upload validation/status rendering vs Python policy enforcement.

## Boundary

- Review and focused refactoring only. No new attachment features, no UI
  redesign, no new supported file formats, no release documentation.
- Extract shared behavior only where an actual invariant or contract is
  duplicated. Do not force abstractions over incidental similarity.
- Preserve user-visible behavior, exception types, event shapes, and error
  messages unless a completed task card explicitly left a bug to fix here.
- If the review finds entropy whose fix would require an architectural
  redesign or behavior change, stop and write a bug report/task follow-up
  instead of folding it into this card.

## Requirements

- Read the completed v1.6.0 diffs and identify duplicated contracts or
  sibling implementations that can drift.
- Record each candidate as one of:
  - real entropy fixed in this task;
  - intentional duplication with reason;
  - out-of-scope follow-up because fixing it changes architecture or
    behavior.
- For each real entropy fix, add or preserve tests that would fail if only
  one side of the duplicated contract changed later.
- Run the standard automated gate after any code change.
- If no entropy is found, update this card with a short "No changes needed"
  note and the evidence reviewed.

## Acceptance criteria

- [ ] The attachment implementation has no unaddressed duplicated contract
      known to this review.
- [ ] Any refactoring preserves existing behavior and error messages.
- [ ] Tests cover every shared invariant extracted or consolidated here.
- [ ] Any intentional duplication or deferred entropy is documented with a
      reason and boundary.
- [ ] `python -m ruff format --check .`, `python -m ruff check .`, and
      `python -m pytest` are green if this card changes code.

