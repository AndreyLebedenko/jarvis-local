# Task: Configuration iteration 2

**Story:** `tasks/story-v1.3.0-control-center.md`
**Status:** Backlog, blocked by task 1 (IA document).
**Release:** v1.3.0

## Summary

Extend the v1.2.4 configuration surface with settings that gained real
engine/config contracts in v1.2.x: TTS engine, TTS language, voice, and VAD
thresholds where supported. All changes flow through the existing layered
config (`config.ui.toml`) and the WS `control` channel.

## Current Boundary

- Add only settings backed by real contracts:
  - `[tts] engine` selection among engines that are actually installed and
    verified (per v1.2.5/v1.2.9 facts in `PROJECT.md`);
  - language and voice options limited to what the selected engine
    supports;
  - VAD thresholds only if the audio config contract exposes them; if not,
    they are absent, not disabled-fake.
- Preserve v1.2.4 semantics: UI writes only the UI config layer;
  restart-to-apply with the visible pending-restart indicator wherever live
  reconfiguration does not exist; dropdowns degrade to the current
  configured value when a source is unavailable.
- Settings UI changes go through the `control` channel (a config command
  family), not a parallel path.
- No live reconfiguration work; if a setting seems to need it, that is a
  story stop condition, not an implementation detail.

## Acceptance Criteria

- [ ] TTS engine/language/voice settings appear only for verified engine
      capabilities and round-trip into `config.ui.toml`.
- [ ] Unsupported combinations are unselectable rather than failing after
      the fact.
- [ ] Restart-to-apply indicator behavior matches iteration 1.
- [ ] Config command handling and payload validation covered by pure tests.
- [ ] `python -m pytest` passes.
- [ ] Manual verification steps prepared for task 4's consolidated QA.

## Stop Conditions

- Stop if a requested setting has no real config or engine contract.
- Stop if a setting requires live reconfiguration not delivered by v1.2.x.
