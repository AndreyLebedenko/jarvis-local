# Task v1.6.0-5: Audio attachments

**Status:** Completed.
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

- [x] Pure tests cover short WAV, stereo-to-mono normalization,
      resampling, over-30-second chunk planning, unsupported/undecodable
      audio, and stable clip ordering.
      `tests/test_attachment_audio.py`, 18 tests: 16 kHz mono round-trip,
      stereo downmix, 44.1 kHz resample with duration preserved, MP3
      through the declared stack, 65 s -> 3 ordered fixed windows with
      exact boundaries and per-clip descriptions, chunking warning,
      exactly-30-s single clip, per-clip <= 30 s decode check, the 90 s
      cap edges (exactly 90 s accepted, one sample over rejected),
      undecodable/zero-sample rejection, media order, cue variants, and
      cue distinctness from `VOICE_PLACEHOLDER_TEXT`.
- [x] Payload tests prove normalized audio clips reach the backend through
      `messages[-1].images`. `tests/test_backend.py::
      test_payload_places_normalized_audio_clips_under_images_of_the_last_message`
      drives a real 65 s WAV through `normalize_audio_attachment()` ->
      `compose_audio_media()` -> `build_payload()` and asserts no `audio`
      field anywhere.
- [x] No microphone behavior changes. `jarvis.audio.input` untouched; the
      only shared code is `jarvis.audio.utils.samples_to_wav_bytes`, the
      dependency-free encoder the policy explicitly names.
- [x] `python -m pytest` and Ruff checks are green.
      Full suite: 1057 passed, 1 skipped. Ruff check and format: clean.

## Outcome

New pure module `src/jarvis/inputs/attachment_audio.py`:
`normalize_audio_attachment(filename, pending)` decodes via `soundfile`
(the same decoder whose header probe the planner ran), downmixes to mono,
resamples to 16 kHz with `torchaudio.functional.resample` (already-declared
stack, no new dependency), splits into deterministic fixed-length <= 30 s
windows (last shorter; never VAD - an uploaded file has no live speech-end
signal), and encodes each clip with the existing
`jarvis.audio.utils.samples_to_wav_bytes` into base64 for the current-turn
`images` payload. Chunking emits a visible warning and per-clip
descriptions ("clip 2 of 3, 30.0-60.0 s") per the policy's never-silent
stance. Decode failures and zero-sample files become deterministic
rejections, never exceptions.

`compose_audio_media()` returns clip base64 strings in order;
`compose_audio_cue()` returns the model-facing cue
("[Attached audio: memo.wav, 2.0 s]" / "... split into 3 clips") -
deliberately distinct from the microphone path's VOICE_PLACEHOLDER_TEXT so
upload never masquerades as realtime listening. The cue is emitted from
the normalization result, not the plan, so it can never name audio whose
decode later failed; `compose_turn_text()`'s comment now records that
contract for task-v1.6.0-6's orchestration to consume.

**Review fix 1:** the normalizer did not re-enforce the policy's
90 s / 3 clip cap on decoded audio - it would have chunked any decoded
length into however many windows it produced, relying entirely on the
planner's `sf.info()` header probe. For compressed formats the decoded
length can differ from the header's claim, and this layer owns chunk
planning "according to policy". Added a guard after `clip_count` is
computed: more than `MAX_CLIPS_PER_FILE` (= `MAX_AUDIO_SECONDS /
MAX_CLIP_SECONDS`, imported from the planner as the single source) is a
deterministic rejection stating the cap and asking the user to trim or
split - never a silent truncation. Tests pin both edges: exactly 90 s is
accepted as 3 clips; 90 s + 1 sample is rejected.

Human review 2026-07-19: one P2 finding (the 90 s / 3 clip cap not
re-enforced after decode), fixed as Review fix 1 above; no further code
findings. Per-clip description presentation is explicitly left for
task-v1.6.0-6 to wire.

