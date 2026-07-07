# Task: Day-0 checks extension for activation and warmup

**Story:** `tasks/story-v1.2.7-activation-and-warmup.md`
**Status:** Backlog.
**Release:** v1.2.7
**Depends on:** `tasks/story-v1.2.7-task-3-ptt-hotkey-trigger.md`,
`tasks/story-v1.2.7-task-4-orb-click-trigger.md`

## Summary

Extend `day0_checks.py` so the human can verify warmup timing and activation
trigger behavior on the real machine.

## Current Boundary

- Agent writes the script/checks and handoff.
- Human runs checks on real hardware.
- The warmup timing output is measurement, not pass/fail.

## Acceptance Criteria

- [ ] Check prints measured `load_duration` for warmup.
- [ ] Check verifies global PTT behavior outside app focus.
- [ ] Check verifies orb click and PTT use the same activation path.
- [ ] Check verifies repeated triggers do not duplicate warmup requests.
- [ ] Output gives clear PASS/FAIL or measured values.
- [ ] Handoff tells the human what to copy into `PROJECT.md`.
- [ ] After human confirmation, measured warmup facts are recorded in
      `PROJECT.md` as verified facts.
- [ ] Automated pure tests pass before handoff.

## Verification

- Run `python -m pytest`.
- Human runs extended `day0_checks.py` and reports output.

## Stop Conditions

- Stop if checks require hardware execution by the agent.
- Stop if measured values are needed before choosing defaults.
- Stop if live failures are environment/tooling issues outside the task.
