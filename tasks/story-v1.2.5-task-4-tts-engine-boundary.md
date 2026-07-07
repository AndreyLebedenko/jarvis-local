# Task: TTS engine boundary

**Story:** `tasks/story-v1.2.5-tts-engine-foundation.md`
**Status:** Backlog.
**Release:** v1.2.5
**Depends on:** `tasks/story-v1.2.5-task-3-record-tts-verified-facts.md`

## Summary

Separate synthesis from sentence buffering and playback orchestration through a
testable TTS engine boundary.

## Current Boundary

- Preserve current Silero behavior by default.
- `TtsOutput` keeps sentence buffering and playback orchestration.
- Silero synthesis moves behind `SileroEngine`.
- Do not add a new production TTS engine in this task unless the recorded facts
  explicitly require it.

## Acceptance Criteria

- [ ] A `TtsEngine` interface or protocol exists.
- [ ] A structured `SynthesisResult` carries audio data and sample rate.
- [ ] `SileroEngine` owns Silero synthesis details.
- [ ] Silero-specific number normalization and Latin transliteration remain
      inside or near the Silero boundary.
- [ ] Existing sentence buffering and playback tests remain meaningful.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if the boundary makes current Silero behavior harder to test.
- Stop if multiple engine abstractions are plausible with non-obvious
  architectural trade-offs.
