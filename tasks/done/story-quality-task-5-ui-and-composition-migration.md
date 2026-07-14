# Task: Migrate UI and composition root

**Story:** `tasks/done/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Move UI contracts, transport, window shells, static assets, and application
composition into `src/jarvis`, then remove the remaining root-level production
modules.

## Acceptance Criteria

- [x] UI assets are resolved from the installed package, not the working
      directory.
- [x] Application composition runs through `python -m jarvis`.
- [x] No root-level production modules remain.
- [x] Pure tests pass; visual/hardware manual verification is handed off.

