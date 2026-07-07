# Task: Document CI and manual check boundary

**Story:** `tasks/story-v1.2.2-project-verification-contract.md`
**Status:** Backlog.
**Release:** v1.2.2
**Depends on:** `tasks/story-v1.2.2-task-2-add-pure-ci-workflow.md`

## Summary

Document which checks are covered by CI and which remain human-run manual
handoffs.

## Current Boundary

- Documentation only.
- Do not add new test infrastructure.
- Do not move manual checks into CI.

## Acceptance Criteria

- [ ] README or project docs list CI-covered pure checks.
- [ ] Docs list hardware/manual checks excluded from CI.
- [ ] Docs point to the existing manual check scripts where appropriate.
- [ ] Docs keep `python -m pytest` as the local automated test command.
- [ ] Docs explain that CI does not prove untested runtime network absence.

## Verification

- Read edited files with `Get-Content -Raw -Encoding UTF8`.
- Run `python -m pytest` unless this remains a docs-only change and the human
  agrees to review without test run.

## Stop Conditions

- Stop if documentation implies CI verifies hardware behavior.
- Stop if documentation implies GitHub Actions proves every runtime locality
  property.
