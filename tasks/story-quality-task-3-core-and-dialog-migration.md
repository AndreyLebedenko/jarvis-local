# Task: Migrate core and dialog modules

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Not started.

## Summary

Move core contracts/configuration and backend/dialog state into package
subdirectories, updating their consumers and tests atomically.

## Acceptance Criteria

- [ ] Core and dialog modules have package-qualified imports.
- [ ] No compatibility copies or aliases remain at the repository root.
- [ ] Pure tests pass.

