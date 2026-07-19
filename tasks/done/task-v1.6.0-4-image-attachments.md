# Task v1.6.0-4: Image attachments

**Status:** Completed.
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

- [x] Pure tests cover accepted PNG/JPG images, malformed image bytes,
      oversize images, too many images, and mixed image/text batches.
      `tests/test_attachments.py`: PNG and JPEG acceptance with byte
      round-trip, non-image bytes behind a `.png` extension, truncated
      signature, oversize (pre-existing, helper now uses the real 8-byte
      PNG signature), per-turn image cap (pre-existing), and cue/media
      composition over mixed image/text/rejected batches.
- [x] A backend payload regression test proves image attachments still
      reach Ollama through `messages[-1].images`, not through a dedicated
      field. `tests/test_backend.py::
      test_payload_places_image_attachments_under_images_of_the_last_message`
      drives a real `plan_attachments()` -> `compose_turn_images()` plan
      through `build_payload()`.
- [x] No UI or journal changes yet. Only `src/jarvis/inputs/attachments.py`
      and the two test files changed; policy doc records the
      no-resize decision it had deferred to this task.
- [x] `python -m pytest` and Ruff checks are green.
      Full suite: 1038 passed, 1 skipped. Ruff check and format: clean.

## Outcome

`_plan_image()` now validates bytes before base64-encoding: a PNG/JPEG
signature sniff, the image analog of the audio path's `soundfile.info()`
header probe - cheap, deterministic, no new dependency (Pillow rejected on
the same stop-condition reasoning as M4A; decision recorded in
`tasks/attachment-policy-v1.6.0.md`). The sniff is class-level, matching
the existing class-level MIME check: a `.png` holding valid JPEG bytes is
accepted because the model receives working bytes either way; genuinely
non-image bytes are rejected with a deterministic message naming the file.

`compose_turn_text()` now emits a short cue (`[Attached image: photo.png]`)
for each accepted image, in plan order interleaved with text-file blocks,
so the model can connect the media to the user's words without any binary
in text. New `compose_turn_images()` returns accepted images' base64
strings in upload order - the exact representation the screenshot path
already feeds the current-turn media list, giving task-v1.6.0-6 a typed
seam to concatenate. Media stays current-turn only; `ConversationHistory`,
backend, UI, and journal are untouched.

Human review 2026-07-19: no code findings. Agreed that no user-run e2e
check is needed at this stage (no transport/UI exists yet); a real `.jpg`
is added to task-v1.6.0-10's manual check list instead, since the live
`images`-field precedent covers PNG only.

