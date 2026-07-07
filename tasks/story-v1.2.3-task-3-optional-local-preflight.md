# Task: Optional local preflight

**Story:** `tasks/story-v1.2.3-hygiene-and-known-debts.md`
**Status:** Backlog.
**Release:** v1.2.3

## Summary

Optionally add a local preflight helper if CI leaves repeated local verification
commands awkward.

## Current Boundary

- This task is optional.
- Prefer wrapping approved project commands.
- Do not create a second source of truth for testing.

## Acceptance Criteria

- [ ] If added, the preflight helper runs `python -m pytest`.
- [ ] If formatter/linter tooling exists in project definition files, the
      helper uses those tools rather than ad-hoc commands.
- [ ] Helper documentation says CI and local preflight are conveniences over
      the same pure checks.
- [ ] Hardware/manual checks remain excluded.
- [ ] `python -m pytest` passes.

## Verification

- Run the new helper if it is added.
- Run `python -m pytest`.

## Stop Conditions

- Stop if no project-approved formatter/linter command exists and adding one
  would expand the task.
- Stop if the helper starts duplicating CI logic in a brittle way.
