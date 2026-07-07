# Task: Control plane manual verification handoff

**Story:** `tasks/story-v1.2.4-status-console-control-plane.md`
**Status:** Backlog.
**Release:** v1.2.4
**Depends on:** `tasks/story-v1.2.4-task-3-config-menu-iteration-1.md`

## Summary

Prepare and document the human-run verification for real WebView shutdown and
real model/microphone source behavior.

## Current Boundary

- Handoff script or instructions only.
- The agent does not run WebView, live Ollama, or real audio-device checks.
- Do not close the story until the human reports results.

## Acceptance Criteria

- [ ] Handoff gives exact command to launch the live Status Console.
- [ ] Handoff explains how to verify guarded shutdown.
- [ ] Handoff explains how to verify model dropdown behavior.
- [ ] Handoff explains how to verify microphone dropdown behavior.
- [ ] Handoff explains expected behavior when local Ollama or audio devices are
      unavailable.
- [ ] Automated pure checks still pass before handoff.

## Verification

- Run `python -m pytest`.
- Human runs the documented manual checks and reports output.

## Stop Conditions

- Stop if manual verification reveals a behavior outside the story boundary.
- Stop if live checks fail due to environment/tooling issues outside the task.
