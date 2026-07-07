# Task: Hotkey dependency and documentation cleanup

**Story:** `tasks/story-v1.2.6-hotkey-provider-migration.md`
**Status:** Backlog.
**Release:** v1.2.6
**Depends on:** `tasks/story-v1.2.6-task-2-migrate-existing-hotkeys.md`

## Summary

Remove the old `keyboard` dependency or document it as an explicit fallback
with privacy trade-offs.

## Current Boundary

- Dependency and docs cleanup only.
- Do not add platform providers.
- Do not change hotkey defaults unless migration data requires it.

## Acceptance Criteria

- [ ] `requirements.txt` no longer includes `keyboard`, or docs explain the
      explicit fallback and privacy trade-off.
- [ ] README known issues are updated to reflect the new hotkey state.
- [ ] `PROJECT.md` is updated if the architectural decision changes.
- [ ] Stale references to the old hotkey model are removed or revised.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Search for stale `keyboard` references and review remaining intentional
  mentions.

## Stop Conditions

- Stop if removing `keyboard` breaks a path not yet migrated.
- Stop if fallback behavior has non-obvious privacy implications.
