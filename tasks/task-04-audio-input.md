# Task: Audio input (audio_in.py)

Status: Not started.

Story: [story-jarvis-v1.0.md](story-jarvis-v1.0.md)

## Summary

Microphone capture plus Silero VAD end-of-utterance detection. Segments
continuous audio into utterance chunks capped at 30 s (PROJECT.md's verified
audio-input limit) and publishes each finished chunk as a wav payload on the
bus.

## Current boundary

In scope:

- VAD-driven segmentation logic, implemented so it can run against
  prerecorded wav bytes with no microphone present (the fixtures
  `audio/a1.wav` and `audio/a2.wav` already in the repo, plus any additional
  synthetic fixtures needed for edge cases: silence-only, an utterance that
  crosses the 30 s boundary).
- A thin microphone-capture layer (e.g. `sounddevice`) that feeds live audio
  into the same segmentation logic; this layer is hardware-dependent and
  covered by the manual handoff, not automated tests.
- VAD thresholds and max chunk length read from `config.py`'s settings
  object.
- Published bus event carries the wav bytes plus segmentation metadata
  (start/end offsets, duration).

Out of scope:

- No wake-word detection; VAD-based start/end-of-utterance only, matching
  PROJECT.md's module description (no hotkey is mentioned for starting
  capture, unlike `capture.py` which is explicitly hotkey-triggered).
- No noise suppression/denoising.
- No multi-microphone-device selection UI; single default input device.

## Dependencies

`bus.py` (task-01), `config.py` (task-02, for VAD thresholds and max chunk
length).

## Acceptance criteria

Automated tests (prerecorded fixtures, no microphone):

- Running the VAD chunker over `audio/a1.wav` and `audio/a2.wav` produces
  the expected utterance boundaries (start/end offsets consistent with an
  independent listen-through by the human during test authoring).
- An utterance longer than 30 s is split into multiple chunks, none
  exceeding the limit.
- A silence-only fixture produces zero published chunks.
- Published bus events carry correct wav byte payloads and metadata for
  each fixture case above.

Manual handoff (microphone-dependent, human runs and reports):

- Exact command to run the live capture loop; confirm real speech triggers
  a chunk publish, silence does not, and end-of-utterance latency feels
  reasonable for a conversational pace.
