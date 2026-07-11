# Task: Modules panel and data axes

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Planned. Blocked by task 1 and by v1.2.14.
**Release:** v1.3.0

## Summary

Grow the module chips into the mock-up's modules panel, driven by the
v1.2.14 health events, and implement the data-source and data-presence
axes from authoritative state only.

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
- Data-presence axis: strictly from events that exist (screenshot
  captured, clipboard submitted, mic awake/asleep); items the IA document
  classified as unavailable are omitted, not approximated.
- Small `ui_contract` deltas approved by the IA document are implemented
  here and folded into the transport snapshot; anything larger stops the
  task.
- Visibility-mode independence: Open/Hidden changes must not alter
  data-source or data-presence display (tests).
- Touchstrip: receives only what the IA document assigned to the glance
  surface, routed through the v1.2.14 capability-based contract.

## Acceptance Criteria

- [ ] Modules panel renders from snapshot data with no hardcoded module
      set; unknown states display honestly.
- [ ] Data-source rendering is value-set-agnostic (asserted by test, not
      by implementing a fake second value).
- [ ] Data-presence items each trace to a named authoritative event.
- [ ] Visibility-mode independence covered by tests.
- [ ] `python -m pytest` passes.
- [ ] Manual verification steps prepared for task 4.

## Stop Conditions

- Stop if an IA-approved element turns out to need more than the recorded
  small contract delta.
- Stop if locality, presence, and visibility semantics conflict in any
  concrete UI state (story stop condition).
