# Task: Authoritative module-health events

**Story:** `tasks/story-v1.2.14-ui-state-foundation.md`
**Status:** Completed.
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

- [x] Backend, TTS, vision, and microphone health all flow through
      `ModuleHealthChanged`; no direct `set_module_health` pushes remain
      outside the transport fold. (Recorded deviation: the microphone
      seed in `wire_status_console()` remains a direct call as the
      initial snapshot value, mirroring task 1's WARMING seed decision -
      see PROJECT.md.)
- [x] Every published health value traces to a named authoritative signal
      (documented in the card or code, asserted in tests).
- [x] A module with no signal yet shows as unknown, never as OK.
- [x] `python -m pytest` passes.

## Verification record

- Automated: 545 passed, Ruff clean (2026-07-11).
- Manual (human-run, 2026-07-11): backend chip OK after warm-up, mic
  chip toggling, vision chip OK after capture, memory honest grey. TTS
  chip showed DEGRADED "synthesis failed" against a genuinely missing
  Silero model cache (environment issue, fixed by setup_tts_model.py),
  then OK after the model was cached - a live validation of both the
  failure and recovery paths.
- Noted for the v1.3.0 IA document: total TTS failure and a single
  skipped unit both display as DEGRADED; an escalation rule was
  deliberately not built here (it would be a heuristic bordering on the
  probes this card forbids).

## Stop Conditions

- Stop if a wanted health value would require a new probe/polling
  mechanism - record the gap; do not build probes in this task.
- Stop if TTS route health cannot be expressed per configured language
  without changing the TTS engine contract.
