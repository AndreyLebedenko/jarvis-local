# Task: Configuration iteration 2

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Planned. Blocked by task 1 (accepted IA document).
**Release:** v1.3.0

## Summary

Extend the configuration surface with the settings that gained real config
contracts in v1.2.x: per-language TTS engine/model routes, UI language,
and VAD settings. Same layered-config semantics as iteration 1.

## Current Boundary

- Settings exposed, each backed by an existing contract in
  `src/jarvis/core/config.py`:
  - per-language TTS route (`TtsLanguageSettings`: engine + model per
    language) - options limited to engines/models the project actually
    supports (see `PROJECT.md` verified TTS facts); unsupported
    combinations unselectable;
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

- [ ] All exposed settings round-trip into `config.ui.toml` and survive
      restart.
- [ ] Invalid VAD values are rejected at the UI and the command handler
      (defense on both sides), with the config unchanged.
- [ ] Pending-restart indicator behavior matches iteration 1 for every
      new setting.
- [ ] `python -m pytest` passes.
- [ ] Manual verification steps prepared for task 4.

## Stop Conditions

- Stop if a setting turns out to need live reconfiguration.
- Stop if TTS route options cannot be derived from real contracts without
  hardcoding engine lists in the UI.
