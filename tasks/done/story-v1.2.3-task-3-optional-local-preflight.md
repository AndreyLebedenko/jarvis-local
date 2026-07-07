# Task: Optional local preflight

**Story:** `tasks/story-v1.2.3-hygiene-and-known-debts.md`
**Status:** Completed (decision: not added).
**Release:** v1.2.3

## Summary

Optionally add a local preflight helper if CI leaves repeated local verification
commands awkward.

## Current Boundary

- This task is optional.
- Prefer wrapping approved project commands.
- Do not create a second source of truth for testing.

## Acceptance Criteria

- [x] If added, the preflight helper runs `python -m pytest`. (N/A - not added)
- [x] If formatter/linter tooling exists in project definition files, the
      helper uses those tools rather than ad-hoc commands. (N/A - none exists)
- [x] Helper documentation says CI and local preflight are conveniences over
      the same pure checks. (N/A - not added)
- [x] Hardware/manual checks remain excluded. (N/A - not added)
- [x] `python -m pytest` passes.

## Verification

- Run the new helper if it is added.
- Run `python -m pytest`.

## Stop Conditions

- Stop if no project-approved formatter/linter command exists and adding one
  would expand the task.
- Stop if the helper starts duplicating CI logic in a brittle way.

## Resolution

Checked the repo for a project-approved formatter/linter: no
`pyproject.toml`, `setup.cfg`, `.flake8`, `ruff.toml`, or lint/format entry
in `requirements.txt` exists. The project's only approved local verification
command is `python -m pytest` (CLAUDE.md's Tooling notes, `.github/workflows/
ci.yml`), already a single, already-trivial command.

Decision: do not add a preflight script. Wrapping a single already-simple
command in a new script would add indirection without reducing any real
friction, and risks becoming a second, independently-maintained copy of
`ci.yml`'s logic that could quietly drift from it (exactly what this task's
own boundary rules out: "do not create a second source of truth for
testing"). This matches the story's framing of the task as optional and its
own stop condition anticipating this exact case (no formatter/linter exists
in project definition files). If a real formatter/linter is adopted later,
or CI grows enough steps that a local wrapper genuinely saves repeated typing,
this task can be revisited then.

No code changes. `python -m pytest` passes unchanged (269 passed).
