# Task: Consolidated visual and manual QA

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Backlog, blocked by tasks 1-3.
**Release:** v1.3.0

## Summary

Prepare the consolidated human-run QA pass covering every Control Center
surface and axis combination. The agent prepares scripts, checklists, and
exact commands; the human runs them and reports results.

## Current Boundary

- Surfaces: desktop Control Center (WebView2 window and Chrome client on
  the same loopback URL) and touchstrip.
- Combinations covered by the checklist:
  - Open/Hidden visibility in both surfaces;
  - data-source and data-presence axis states that exist;
  - configuration iteration 2 flows including restart-to-apply;
  - modules panel with the real module list from the state snapshot;
  - telemetry panel if the IA document kept it, showing real engine-side
    values.
- Extend or reuse the demo/QA harness for state coverage where a live
  engine state is hard to trigger on demand, keeping the harness dev-only.
- No fake-success checks: every checklist item verifies a real capability;
  anything that cannot be demonstrated honestly is a finding, not a pass.
- Findings that will not be fixed in v1.3.0 are written up per the
  bug-report protocol under `tasks/bug_reports/`.

## Acceptance Criteria

- [ ] QA checklist covers all surface/axis/config combinations above with
      exact human-run commands.
- [ ] Automated tests cover harness/script wiring that does not need
      hardware or a real window.
- [ ] `python -m pytest` passes.
- [ ] Human has run the checklist; results and any bug reports recorded.
- [ ] Story acceptance criteria checked off against the QA results before
      the story closes.

## Stop Conditions

- Stop if QA reveals overlapping text or unreadable touchstrip states
  (story stop condition).
- Stop if any checklist item can only pass by faking capability.
