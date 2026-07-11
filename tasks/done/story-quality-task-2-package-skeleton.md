# Task: Add package skeleton and entry point

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Create the installable `src/jarvis` package, packaging metadata, and
`python -m jarvis` entry point without migrating subsystem implementations.

## Acceptance Criteria

- [x] Editable installation exposes `jarvis` independently of the repository
      working directory.
- [x] `python -m jarvis` delegates to the existing application entry point.
- [x] Pure tests pass without duplicating production implementations.

## Verification

- `python -m pip install -e . --no-deps` installs `local-jarvis` and exposes
  `jarvis` from an unrelated working directory.
- `python -m jarvis --help` delegates to the existing application CLI from an
  unrelated working directory.
- `python -m pytest`: 527 passed.

## Transitional Packaging Boundary

Setuptools temporarily installs the existing root production files as
`py-modules`, while `jarvis.__main__` delegates to top-level `main`. This is a
single-source transition state, not a compatibility copy. Tasks 3-5 remove
entries from that list as implementations move into `src/jarvis`; Task 5
removes the transitional top-level module boundary entirely.

