# Task: Compare PCM16 and float32 WAV decoding for short audio

**Status:** In progress.

## Summary

Extend the existing human-run audio request-shape harness so the same decoded
16 kHz mono samples can be sent as either WAV `PCM_16` or WAV `FLOAT`. The
comparison tests whether Ollama's WAV decoding path, rather than the existing
PCM16 source quantization, changes short-audio transcription outcomes.

## Boundary

This is a harness-only encoding comparison. Existing journal fixtures are
already PCM16, so re-encoding them as float32 cannot recover precision lost at
microphone-recording time. It must not be described as a test of microphone
capture precision. Changing production microphone or TTS encoding is out of
scope.

## Acceptance criteria

1. `--wav-subtype pcm16` preserves the current payload bytes and behavior.
2. `--wav-subtype float32` decodes the same source samples and sends a 16 kHz,
   mono WAV with `FLOAT` subtype.
3. JSONL metadata and sanitized payload hashes identify the requested subtype
   and exact media bytes used.
4. Pure automated tests verify format conversion and the injected live gateway
   path without calling Ollama.
5. A human runs the two subtype conditions against the same model digests and
   Ollama version before any result is interpreted.
