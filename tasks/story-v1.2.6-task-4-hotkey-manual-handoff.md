# Task: Hotkey manual verification handoff

**Story:** `tasks/story-v1.2.6-hotkey-provider-migration.md`
**Status:** Backlog.
**Release:** v1.2.6
**Depends on:** `tasks/story-v1.2.6-task-3-hotkey-dependency-docs.md`

## Summary

Prepare human-run verification for native global hotkeys on the real Windows
machine.

## Current Boundary

- Handoff instructions and optional check script only.
- The agent does not run global hotkey hardware checks.
- Do not close the release story until the human reports results.

## Acceptance Criteria

- [ ] Handoff covers Administrator and non-Administrator behavior.
- [ ] Handoff covers focus-independent hotkey triggering.
- [ ] Handoff covers registration conflict behavior.
- [ ] Handoff covers each migrated hotkey.
- [ ] Handoff explains what output or observations to report.
- [ ] Automated pure tests pass before handoff.

## Verification

- Run `python -m pytest`.
- Human runs the documented checks and reports results.

## Stop Conditions

- Stop if manual checks reveal provider behavior that conflicts with the
  documented architecture.
- Stop if failures are caused by OS/environment issues outside the task.
