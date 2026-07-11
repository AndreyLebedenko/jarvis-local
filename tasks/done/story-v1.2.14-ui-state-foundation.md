# Story v1.2.14: UI State Foundation

**Status:** Completed (2026-07-11). Tasks 1-2 implemented and verified
live; task 3 closed as obsolete - its defect was already resolved by the
v1.2.10 bridge removal.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.14

## Goal

Give the v1.3.0 Control Center an honest engine-side foundation: a single
owner for RuntimeState transitions, authoritative module-health events for
the modules the engine can actually vouch for, and a clean per-capability
surface contract. This is the architectural prerequisite extracted from
v1.3.0 per its own boundary rule ("no new engine architecture inside
v1.3.0"), combining two existing entropy-review debts with the deferred
ModuleHealth question from the Status Console story.

## Boundaries

- Engine and contract work only. No new UI panels, no visual changes;
  existing surfaces keep rendering exactly what they render today, fed by
  the new events instead of scattered closures where applicable.
- Health is reported only where an authoritative signal exists (module
  init success/failure, real operation success/failure). No polling
  loops, no synthetic health, no telemetry collection (CPU/GPU/RAM was
  explicitly dropped from v1.3.0 and is not smuggled in here).
- The memory module has no engine implementation and therefore gets no
  health source; the five-module set in `ui_contract` stays as data, but
  the engine only publishes what it can vouch for.

## Acceptance Criteria

- [x] One module owns every RuntimeState transition; wire closures contain
      no busy-guard duplication.
- [x] Backend, TTS, and vision publish health events from authoritative
      signals; the transport snapshot reflects them; unpublished modules
      appear as honestly unknown, not as fake OK.
- [x] No `NotImplementedError` capability overrides remain in the window
      surface hierarchy (pre-existing since v1.2.10; task 3 closure note).
- [x] Existing regression tests (stuck-orb, dedup) still pass;
      `python -m pytest` passes (545, plus live human verification of
      both tasks).

## Task Card Sequence

1. `story-v1.2.14-task-1-runtime-state-tracker.md`
   Single owner for RuntimeState transitions (from entropy-review backlog).
2. `story-v1.2.14-task-2-module-health-events.md`
   Authoritative module-health events for backend, TTS, and vision.
3. `story-v1.2.14-task-3-touchstrip-capability-composition.md`
   Capability-based surface contract instead of inheritance-with-holes
   (from entropy-review backlog).

## Stop Conditions

- Stop if a module has no authoritative health signal and one would have
  to be invented - record the gap instead.
- Stop if the tracker cannot express an existing transition without new
  lifecycle events beyond those listed in its card.
