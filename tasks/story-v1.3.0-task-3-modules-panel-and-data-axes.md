# Task: Modules panel and data axes

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Planned. Blocked by v1.2.16 model-request composition state.
**Release:** v1.3.0

## Summary

Grow the module chips into the mock-up's modules panel, driven by the
v1.2.14 health events, and implement the data-source and last-request axes
from authoritative state only.

## Current Boundary

- Modules panel:
  - rendered data-driven from the snapshot's module-health list; adding a
    module later is an engine/contract change, not a markup change;
  - health states shown are exactly the v1.2.14 vocabulary including
    honest unknown; no OK badge without a signal;
  - per-module detail text comes from the health event's detail field
    (already localized via the `ui_text` catalog).
- Data-source axis: renders the locality value set from the snapshot
  without assuming it is binary; v1.3.0 only ever shows the existing
  local value; a rendering test proves a new value needs no markup
  change.
- Last-request axis: renders only v1.2.16's exact accepted request
  composition. Each row starts with its local timestamp, then identifies the
  sent source; voice also shows total duration. It never reports a live
  microphone state, captured-but-pending screenshot, rejected clipboard, or
  model-response success.
- Task 3 consumes v1.2.16's typed transport snapshot; it adds no second
  request-composition contract or parallel state derivation.
- Visibility-mode independence: Open/Hidden changes must not alter
  data-source or last-request display (tests).
- Touchstrip: receives only what the IA document assigned to the glance
  surface, routed through the v1.2.14 capability-based contract.

## Acceptance Criteria

- [ ] Modules panel renders from snapshot data with no hardcoded module
      set; unknown states display honestly.
- [ ] Data-source rendering is value-set-agnostic (asserted by test, not
      by implementing a fake second value).
- [ ] Last-request items each trace to the v1.2.16 request-composition event;
      timestamps render first and voice duration is honest.
- [ ] Visibility-mode independence covered by tests.
- [ ] `python -m pytest` passes.
- [ ] Manual verification steps prepared for task 4.

## Stop Conditions

- Stop if an IA-approved element turns out to need more than the recorded
  small contract delta.
- Stop if locality, last-request, and visibility semantics conflict in any
  concrete UI state (story stop condition).
