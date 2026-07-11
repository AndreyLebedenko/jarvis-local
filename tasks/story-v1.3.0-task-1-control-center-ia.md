# Task: Control Center information architecture

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Planned. May run in parallel with v1.2.14 (document-only).
**Release:** v1.3.0

## Summary

Produce the design decision document that tasks 2-4 treat as their
requirements source: map every element of
`.planning/UI/mock-ups/jarvis_dashboard_v3.html` onto the evolved Status
Console page, classify it against real engine state, and fix desktop vs
touchstrip placement. Deliverable is a document, not code.

## Current Boundary

- Fixed inputs (human decisions, not up for re-litigation here):
  - Control Center is an evolution of the existing Status Console page;
  - CPU/GPU/RAM telemetry panel: dropped from v1.3.0;
  - memory/vector-store panel: dropped (no engine capability);
  - module health arrives via v1.2.14 `ModuleHealthChanged` events.
- For every remaining mock-up element, record one of: backed by
  authoritative state now / small `ui_contract` delta in scope for task 3
  / dropped or visibly disabled. Name the state source for each kept
  element.
- Modules panel is data-driven: the UI renders the module list from the
  snapshot; no hardcoded module set in markup.
- Data-locality presentation must not assume a binary local/cloud set
  (v1.4.0 adds the first external value).
- Reserve layout space for the hidden-by-default dangerous-capabilities
  section (no implementation, per story boundary).
- Decide desktop vs touchstrip placement for every control; touchstrip
  stays a glance/control surface.
- Output lives under `.planning/UI/` or `tasks/`; human review required
  before task 2 starts.

## Acceptance Criteria

- [ ] Every dashboard-v3 element is classified with its state source
      named, or its removal recorded.
- [ ] Any "small delta" items are listed with exact contract additions
      small enough for task 3.
- [ ] Placement decided for every control; reservation slot documented.
- [ ] Human has reviewed and accepted the document.

## Stop Conditions

- Stop if an element considered essential has no honest state source and
  exceeds a small contract delta - that is new v1.2.x prep work, not a
  task-3 item.
- Stop if placement conflicts with the touchstrip glance-surface rule.
