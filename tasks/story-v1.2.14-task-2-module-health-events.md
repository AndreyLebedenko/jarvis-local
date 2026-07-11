# Task: Authoritative module-health events

**Story:** `tasks/story-v1.2.14-ui-state-foundation.md`
**Status:** Planned. Runs after task 1 (same ownership pattern).
**Release:** v1.2.14

## Summary

Close the deferred ModuleHealth question from the Status Console story:
backend, TTS, and vision publish health events derived from authoritative
signals they already have, so the v1.3.0 modules panel can render real
state instead of the current microphone-only snapshot.

## Current Boundary

- A `ModuleHealthChanged` bus event carrying the existing
  `ui_contract.ModuleHealth` shape; the transport folds it into the
  snapshot/delta stream it already sends.
- Sources are strictly signals the modules already produce:
  - backend: warm-up outcome, request/stream failures, recovery on the
    next successful turn;
  - TTS: engine/model load outcome per configured language route,
    synthesis failures;
  - vision: screen-capture outcome on actual capture attempts;
  - microphone: the existing awake/asleep source, migrated to the same
    event path so there is one mechanism, not two.
- No polling, no probes, no synthetic OK: a module that has produced no
  signal yet is reported as unknown/pending, and the UI already has
  honest states for that.
- Memory publishes nothing (no engine implementation exists).
- Pure tests: each source's mapping from module signal to health event,
  transport folding, and the unknown-before-first-signal behavior.

## Acceptance Criteria

- [ ] Backend, TTS, vision, and microphone health all flow through
      `ModuleHealthChanged`; no direct `set_module_health` pushes remain
      outside the transport fold.
- [ ] Every published health value traces to a named authoritative signal
      (documented in the card or code, asserted in tests).
- [ ] A module with no signal yet shows as unknown, never as OK.
- [ ] `python -m pytest` passes.

## Stop Conditions

- Stop if a wanted health value would require a new probe/polling
  mechanism - record the gap; do not build probes in this task.
- Stop if TTS route health cannot be expressed per configured language
  without changing the TTS engine contract.
