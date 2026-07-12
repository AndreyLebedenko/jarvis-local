# Task: Configuration iteration 2

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Completed.
**Release:** v1.3.0

## Summary

Extend the configuration surface with the settings that gained real config
contracts in v1.2.x: fully typed per-language TTS routes, UI language,
and VAD settings. Same layered-config semantics as iteration 1.

## Current Boundary

- Settings exposed, each backed by an existing contract in
  `src/jarvis/core/config.py`:
  - per-language TTS route (`SileroTtsSettings | PiperTtsSettings`): engine,
    model, and every parameter owned by that engine type. The form schema is
    projected from the same dataclass fields and constraints used by TOML
    validation; the front-end does not maintain a parallel parameter list;
  - `[ui].language` (en/ru, v1.2.11);
  - `VadSettings`: threshold, max_chunk_seconds,
    request_end_pause_seconds, resume_cooldown_seconds - numeric inputs
    with validated ranges, not free text.
- Iteration-1 semantics preserved exactly: UI writes only the UI config
  layer; restart-to-apply with the visible pending-restart indicator;
  sources degrade to the configured value when unavailable.
- Changes ride the existing WS `control` channel config command family;
  no new transport or engine behavior.
- `[prompts]` (v1.2.12) is out of scope for the UI in this iteration:
  multi-line prompt editing is a different control surface; revisit only
  if the human asks.
- Pure tests: command payload validation, range validation, config-layer
  write-through, degraded-source behavior.

## Acceptance Criteria

- [x] All exposed settings round-trip into `config.ui.toml` and survive
      restart.
- [x] Switching the TTS engine switches the complete parameter form to that
      engine's typed contract; arbitrary non-empty Silero models are accepted.
- [x] Invalid VAD values are rejected at the UI and the command handler
      (defense on both sides), with the config unchanged.
- [x] Pending-restart indicator behavior matches iteration 1 for every
      new setting.
- [x] `python -m pytest` passes.
- [x] Manual verification completed by the human: the full typed TTS form,
      restart-to-apply, and persisted configuration work on the live system.

## Stop Conditions

- Stop if a setting turns out to need live reconfiguration.
- Stop if TTS route fields, types, or constraints cannot be projected from
  the real config contract without a parallel UI schema.
