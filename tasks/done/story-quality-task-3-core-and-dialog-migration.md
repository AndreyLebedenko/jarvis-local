# Task: Migrate core and dialog modules

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Move core contracts/configuration and backend/dialog state into package
subdirectories, updating their consumers and tests atomically.

## Acceptance Criteria

- [x] Core and dialog modules have package-qualified imports.
- [x] No compatibility copies or aliases remain at the repository root.
- [x] Pure tests pass.

## Verification

- No Python file imports the removed top-level `bus`, `config`, `system_log`,
  `backend`, or `thinking_mode` modules.
- `python -m jarvis --help` works from an unrelated working directory.
- `python -m pytest`: 527 passed.

## Transitional Boundary

`jarvis.core.system_log` still imports the top-level `ui_contract` scheduled
for Task 5, and `jarvis.dialog.thinking_mode` still imports the top-level
`hotkey_provider` scheduled for Task 4. Both dependencies point outward in one
direction; no reverse import or cycle was introduced.

