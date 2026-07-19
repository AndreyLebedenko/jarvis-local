# Task v1.6.0-4: Image attachments

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-2.

## Summary

Implement image attachment handling for the current-turn media path: validate
supported image files, base64-encode accepted bytes, and preserve the
verified Ollama rule that images go through the `images` field.

## Context you need

- task-v1.6.0-1 policy for supported image extensions, byte limits, and
  per-turn image count.
- `src/jarvis/dialog/backend.py`: `build_payload()` attaches `images` only
  to the final user message.
- `src/jarvis/app.py`: screenshots already become current-turn media and
  never enter `ConversationHistory`.
- `tests/test_backend.py` or nearby backend payload tests for the existing
  images-field regression style.

## Boundary

- Image validation and current-turn media planning only. No UI endpoint,
  no thumbnail rendering, no OCR, no image resizing unless task-v1.6.0-1
  explicitly selected it.
- Do not change the backend's `images` field contract.
- Do not persist uploaded image bytes in `ConversationHistory`.

## Requirements

- Validate image attachments by policy, not by trusting extension alone.
- Convert accepted image bytes into the same media representation used by
  screenshots.
- Keep media order stable relative to other planned media.
- Include a small text cue in the model-facing user content that names the
  attached image files, without embedding binary data in text.
- Reject unsupported or malformed images clearly.

## Acceptance criteria

- [ ] Pure tests cover accepted PNG/JPG images, malformed image bytes,
      oversize images, too many images, and mixed image/text batches.
- [ ] A backend payload regression test proves image attachments still
      reach Ollama through `messages[-1].images`, not through a dedicated
      field.
- [ ] No UI or journal changes yet.
- [ ] `python -m pytest` and Ruff checks are green.

