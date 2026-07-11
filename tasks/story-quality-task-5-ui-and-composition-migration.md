# Task: Migrate UI and composition root

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Not started.

## Summary

Move UI contracts, transport, window shells, static assets, and application
composition into `src/jarvis`, then remove the remaining root-level production
modules.

## Acceptance Criteria

- [ ] UI assets are resolved from the installed package, not the working
      directory.
- [ ] Application composition runs through `python -m jarvis`.
- [ ] No root-level production modules remain.
- [ ] Pure tests pass; visual/hardware manual verification is handed off.

