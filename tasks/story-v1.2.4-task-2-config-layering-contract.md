# Task: Configuration layering contract

**Story:** `tasks/story-v1.2.4-status-console-control-plane.md`
**Status:** Backlog.
**Release:** v1.2.4
**Depends on:** `tasks/story-v1.2.4-task-1-shutdown-control.md`

## Summary

Define and test configuration precedence for built-in defaults, user config,
and UI-written config.

## Current Boundary

- Config contract only.
- Do not build the menu UI in this task.
- Do not implement live reconfiguration.

## Acceptance Criteria

- [ ] Config precedence is built-in defaults, `config.toml`, then
      `config.ui.toml`.
- [ ] The UI config layer is the only layer intended for Status Console writes.
- [ ] Restart-to-apply is recorded in `PROJECT.md`.
- [ ] Pure tests cover precedence and missing-file behavior.
- [ ] Existing config behavior remains compatible when `config.ui.toml` is
      absent.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if precedence conflicts with existing config loading assumptions.
- Stop if restart-to-apply cannot be expressed without changing live runtime
  behavior.
