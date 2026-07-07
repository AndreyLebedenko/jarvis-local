# Task: TTS config shape

**Story:** `tasks/story-v1.2.5-tts-engine-foundation.md`
**Status:** Backlog.
**Release:** v1.2.5
**Depends on:** `tasks/story-v1.2.5-task-4-tts-engine-boundary.md`

## Summary

Add configuration shape for selecting a TTS engine while preserving current
Silero defaults.

## Current Boundary

- Config shape only.
- Do not expose Control Center UI controls yet.
- Do not implement multilingual request-language behavior.

## Acceptance Criteria

- [ ] Config supports `[tts] engine`.
- [ ] Config supports engine-specific subsections.
- [ ] Default config remains equivalent to current Silero behavior.
- [ ] `config.example.toml` documents the new shape.
- [ ] Tests cover default loading and engine-specific config parsing.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if config shape depends on an unresolved TTS engine choice.
- Stop if config parsing needs type-erasure or unclear defaults.
