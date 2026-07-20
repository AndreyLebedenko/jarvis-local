# Task v1.6.0-1: Attachment policy and format gate

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.0-file-attachments.md`
**Depends on:** roadmap readiness for v1.6.0; no code task dependencies.

## Summary

Turn the story's preliminary attachment scope into explicit first-iteration
policy: supported file classes, byte and duration limits, truncation/chunking
rules, and the dependency decision for compressed audio formats.

## Context you need

- `tasks/done/story-v1.6.0-file-attachments.md`: user-facing goal,
  boundaries, and stop conditions.
- `tasks/roadmap-v1.5.1-v1.7.md`: v1.6.0 entry point is the Journal input
  dock; no new hotkey.
- `PROJECT.md`: verified Ollama media facts. Audio and images both go
  through the `/api/chat` `images` field.
- `requirements.txt`: existing audio stack includes `soundfile`,
  `torchaudio`, and `torch`; do not add another decoder dependency
  without a recorded decision.

## Boundary

- Planning and small capability checks only. No production UI, transport,
  or orchestration changes.
- Do not silently choose broad document ingestion. PDF, DOCX, archive
  files, and long-form media summarization remain out of scope.
- Stop if MP3/M4A support requires a large parser/runtime dependency or
  an external executable that has non-obvious install/runtime trade-offs.

## Requirements

- Decide the exact first-iteration supported extensions and MIME types for:
  audio, image, and text.
- Decide maximum upload size, maximum text characters sent to the model,
  maximum normalized audio seconds per model clip, and maximum number of
  clips/images per turn.
- Decide how unsupported files, oversize files, text truncation, and audio
  chunking are represented to the user.
- Empirically check whether the existing installed stack can decode WAV,
  MP3, and M4A in this project environment without a new dependency. Keep
  the check local and deterministic where possible; do not call Ollama.
- Record the policy in the story card or a small task-local design note
  referenced by later cards.

## Acceptance criteria

- [x] The first-iteration attachment policy is written down with numeric
      limits and explicit supported/unsupported format lists.
      See `tasks/attachment-policy-v1.6.0.md`.
- [x] The compressed-audio dependency decision is recorded; if unresolved,
      later implementation cards are explicitly blocked.
      MP3: supported, no new dependency. M4A: deferred, task-v1.6.0-5 is
      blocked on it pending a human dependency decision. See
      `tasks/attachment-policy-v1.6.0.md` and the new `PROJECT.md`
      verified-facts entry.
- [x] A small pure or local check proves which existing decoder paths are
      available for the selected audio formats.
      `tests/test_audio_decoder_formats.py`, part of `python -m pytest`.
- [x] No production behavior changes in this card.
      Only `tests/`, `tasks/`, `PROJECT.md`, and one new committed audio
      fixture (`audio/sample.m4a`) changed; no `src/jarvis/` edits.

## Outcome

Policy recorded in `tasks/attachment-policy-v1.6.0.md`. Format-gate proof
in `tests/test_audio_decoder_formats.py` (4 new tests, full suite still
green: `python -m pytest` -> 995 passed, 1 skipped before this task's
tests, +4 after). Ruff clean. New verified fact recorded in `PROJECT.md`.
`story-v1.6.0-file-attachments.md`'s preliminary scope updated to point at
the M4A deferral instead of listing it as supported.

Awaiting human review before this card is marked `Completed.` and moved to
`tasks/done/`, per the standard task-card workflow.

