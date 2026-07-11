# Task: Add package skeleton and entry point

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Not started.

## Summary

Create the installable `src/jarvis` package, packaging metadata, and
`python -m jarvis` entry point without migrating subsystem implementations.

## Acceptance Criteria

- [ ] Editable installation exposes `jarvis` independently of the repository
      working directory.
- [ ] `python -m jarvis` delegates to the existing application entry point.
- [ ] Pure tests pass without duplicating production implementations.

