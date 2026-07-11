# Task: Control Center information architecture

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Backlog, blocked by v1.2.10 UI transport.
**Release:** v1.3.0

## Summary

Design the Control Center's information architecture before any
implementation: which engine capabilities exist and are authoritative after
v1.2.x, which controls live on desktop versus touchstrip, and how the
dashboard mock-up (`.planning/UI/mock-ups/jarvis_dashboard_v3.html`) maps
onto real state. The deliverable is a design decision document, not code.

## Current Boundary

- Inventory only capabilities that actually exist: verification contract,
  shutdown/control plane, config layering, TTS engine boundary, unified
  hotkeys, WS transport channels.
- For every mock-up element, record one of: backed by authoritative state
  now / needs a small engine event that is in scope / not implementable
  honestly in v1.3.0 (dropped or visibly disabled).
- Design constraints fixed by the story:
  - modules panel is data-driven: the UI renders the module list from the
    state snapshot, no hardcoded module set in markup;
  - host telemetry (CPU/GPU/RAM), if kept, is collected engine-side and
    published as bus events over the `state` channel - never measured by
    the UI client; if no engine-side source is in scope, the panel is
    dropped from v1.3.0 rather than faked;
  - data-locality presentation must not assume a binary local/cloud set.
- Decide desktop versus touchstrip placement for every control; touchstrip
  remains a glance/control surface, not a miniature dashboard.
- Output: an IA document under `tasks/` (or `.planning/`) that task cards
  2-4 treat as their requirements source.

## Acceptance Criteria

- [ ] Every dashboard mock-up element is classified (real / small event
      needed / dropped-disabled) with the authoritative state source named.
- [ ] Any "small event needed" items are listed with their exact contract
      additions, small enough to stay inside v1.3.0's no-new-architecture
      boundary.
- [ ] Desktop/touchstrip placement decided for every control.
- [ ] The three design constraints above are reflected in the IA document.
- [ ] Human has reviewed and accepted the IA document.

## Stop Conditions

- Stop if an element considered essential has no honest state source and
  its enabling work exceeds the v1.3.0 boundary - move that work to a
  v1.2.x preparation release per the story rule.
- Stop if desktop/touchstrip placement conflicts with the touchstrip
  glance-surface requirement.
