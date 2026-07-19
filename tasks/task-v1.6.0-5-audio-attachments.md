# Task v1.6.0-5: Audio attachments

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-1, task-v1.6.0-2.

## Summary

Implement uploaded audio normalization and chunk planning so accepted audio
files become model-safe clips that use the same verified Ollama media field
as microphone audio.

## Context you need

- `PROJECT.md`: audio constraints are 16 kHz mono wav clips, max 30 s per
  clip; audio and images both go through `/api/chat` `images`.
- `src/jarvis/audio/input.py`: microphone chunks and VAD behavior are
  realtime capture concerns; do not reuse them for uploaded files unless
  the dependency is genuinely pure and simple.
- `src/jarvis/app.py`: microphone turns use `VOICE_PLACEHOLDER_TEXT` and
  current-turn media.
- task-v1.6.0-1 format and dependency decision.

## Boundary

- Uploaded file audio only. No realtime listening changes, no STT, no
  VAD redesign, no microphone path changes.
- No UI endpoint and no JavaScript.
- If selected compressed formats cannot be decoded with the approved stack,
  stop and report the policy/dependency conflict instead of adding a
  workaround.

## Requirements

- Decode selected audio formats into PCM samples with deterministic error
  reporting.
- Normalize to 16 kHz mono wav bytes.
- Split audio into model-safe clips according to task-v1.6.0-1 policy.
- Preserve clip order and generate visible warnings when chunking occurs.
- Prepare base64 media values for the current-turn `images` field.
- Keep uploaded-audio handling distinct from microphone listening in source
  labels and user-visible text.

## Acceptance criteria

- [ ] Pure tests cover short WAV, stereo-to-mono normalization,
      resampling, over-30-second chunk planning, unsupported/undecodable
      audio, and stable clip ordering.
- [ ] Payload tests prove normalized audio clips reach the backend through
      `messages[-1].images`.
- [ ] No microphone behavior changes.
- [ ] `python -m pytest` and Ruff checks are green.

