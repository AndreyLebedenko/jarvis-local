# Task: Apply repository-wide formatting

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Apply Ruff formatting in one isolated mechanical change after the package
migration, so movement history and behavior changes remain reviewable.

## Current Boundary

- Formatting only; no manual cleanup, refactoring, or behavior changes.
- Run after all production modules and tests use the final package paths.
- Keep the change separate from lint fixes and CI enforcement.

## Acceptance Criteria

- [x] `python -m ruff format --check .` passes.
- [x] The diff contains formatting changes only.
- [x] `python -m pytest` passes.

