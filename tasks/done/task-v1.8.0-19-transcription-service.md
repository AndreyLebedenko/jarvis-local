# Task v1.8.0-19: Historical transcription service

**Status:** Completed.
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

- [x] Pure tests cover request construction and job state.
- [x] The service refuses missing media and non-audio events clearly.
- [x] Concurrency limits are enforced.
- [x] Transcript writes are source-grounded and bounded.
- [x] Manual handoff command is provided for live Ollama verification.

## Stop conditions

- Stop if transcription cannot be scheduled without unpredictable live-turn
  latency or VRAM pressure.
- Stop if Ollama audio transport behavior contradicts `PROJECT.md`.

## Verification

- Pure service tests with fake backend.
- Manual local Ollama handoff.
- `python -m pytest`
- Ruff checks.

## Implementation notes

- New module `src/jarvis/journal/transcription.py`, `TranscriptionService`
  with injected seams (`TranscriptionEventSource`, `TranscriptionInferenceBackend`,
  `TranscriptWriter`) so request construction and job state are pure-testable
  without live Ollama. Adapter `OllamaTranscriptionBackend` wraps `iter_chat`.
- Media transport: audio (`.wav`) goes through `images`; the model call runs
  with reasoning off, reads only `message.content`, and never publishes
  `ResponseToken` - transcription stays off the dialog/TTS path.
- Audio is passed through as stored: voice-turn `.wav` is already 16 kHz mono
  <= 30 s (JournalRecorder). Decoding/resampling arbitrary formats is out of
  scope; `AUDIO_MEDIA_EXTENSIONS = {".wav"}`.
- Metadata (model, reasoning, options) is sourced from the backend's own
  `build_payload`, returned via `TranscriptionRun.metadata`, recorded on the
  result and the audit log, and preserved on a stream failure through
  `TranscriptionBackendError`. It is not persisted into the overlay schema
  (task-18 schema unchanged); persistence, if wanted, is a later API/UI
  concern.
- Bounded concurrency via a semaphore (default 1) around the model call only.
  Cancellation: explicit `cancel(ref)`/`cancel_all()`; a joined waiter's own
  cancellation never aborts the shared job; the overlay write is a point of no
  return so a `CANCELLED` result never coexists with a committed write; the
  `_active` entry is cleared on the shared task's actual completion.
- Overlay writes use `TranscriptSource.GENERATED` and are bounded by the
  task-18 size cap (over-limit -> `TRANSCRIPT_REJECTED`, retryable via re-run).
- Not wired into `app.py`/config (UI and projection integration are task-20);
  `manual/manual_check_transcription_service.py` is the live handoff.
