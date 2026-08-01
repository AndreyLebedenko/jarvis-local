# Task v1.8.0-19: Historical transcription service

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-18.

## Summary

Add explicit, non-dialog local Ollama transcription for historical audio with
bounded concurrency and auditable writes to transcript overlays.

## Current boundary

In scope: service API, job bounds, media lookup, local Ollama request shape,
concurrency, cancellation, status reporting, and manual handoff.

Out of scope: background scheduler, automatic audio deletion, annotation
generation, retrieval projection integration, and UI.

## Requirements

- Transcribe only through explicit user/UI command.
- Use the verified Ollama media transport: audio goes through `images`.
- Avoid competing unpredictably with live dialog.
- Write results only to transcript overlays.
- Record model/configuration metadata and source references.
- Keep failures auditable and retryable.
- Do not delete audio after transcription in this task.

## Acceptance criteria

- [ ] Pure tests cover request construction and job state.
- [ ] The service refuses missing media and non-audio events clearly.
- [ ] Concurrency limits are enforced.
- [ ] Transcript writes are source-grounded and bounded.
- [ ] Manual handoff command is provided for live Ollama verification.

## Stop conditions

- Stop if transcription cannot be scheduled without unpredictable live-turn
  latency or VRAM pressure.
- Stop if Ollama audio transport behavior contradicts `PROJECT.md`.

## Verification

- Pure service tests with fake backend.
- Manual local Ollama handoff.
- `python -m pytest`
- Ruff checks.
