# Task: bound the capture buffer so long silence cannot overload VAD

**Status:** Completed.
**Branch:** `task-fix-mic-silence-buffer-vad-overload`.
**Resolves:**
`tasks/bug_reports/2026-07-18-microphone-post-mute-first-capture-degraded.md`
(root cause identified 2026-07-18; see that report's root-cause section).

## Summary

`run_microphone_loop()` trims its accumulated buffer only after an
utterance is published. During any long speech-free period (hardware mute
delivering silence frames, or simply a quiet room), the buffer grows
without bound and `VadChunker.chunk()` re-scans the entire buffer on every
0.3 s block. Measured on the dev machine, the scan crosses the 0.3 s
real-time budget at roughly a 35-40 s buffer and costs about 1.5 s per
block at 180 s. The reader falls behind, the PortAudio input ring
overflows (the overflow flag from `stream.read()` is discarded), and the
first utterance after the silence is published from spliced, degraded
audio. The first publish trims the buffer, which is why the immediately
following capture is clean again.

## Boundary

- `src/jarvis/audio/input.py` only: buffer trimming policy inside the
  microphone loop, plus logging the previously discarded overflow flag.
- Pure regression tests in `tests/test_audio_in.py`.
- No VAD algorithm change, no streaming-VAD redesign, no change to
  publish/merge/cap semantics, no change to sleep/pause hygiene.

## Fix

After each block is processed, trim the buffer past audio that can no
longer contribute to a future utterance:

- if VAD reports an unpublished (still-extending) segment, keep from that
  segment's start minus a 1.0 s lead-in;
- if VAD reports no unpublished segment, keep only the trailing 1.0 s of
  the buffer as lead-in context for speech that may start next block;
- never trim less than the existing published-utterance trim.

This bounds the per-block VAD cost by `max_chunk_seconds` plus the
end-pause instead of by elapsed silence time. Additionally, log a warning
when `stream.read()` reports an input overflow, so a future capture-side
lag is visible in logs instead of silent.

## Acceptance criteria

1. Pure test: with a chunker that never finds speech, the sample count
   passed to `chunk()` stays bounded across many silence blocks.
2. Pure test: speech preceded by a long trimmed silence still publishes
   exactly one utterance with correct duration (no clipped onset).
3. Existing `tests/test_audio_in.py` suite stays green unchanged.
4. Human-run verification (hardware handoff):
   - repeat the device-matrix mute scenario (mute ~3 min, unmute, dictate
     immediately): first capture is clean;
   - control run without mute: stay silent ~3 min, then dictate: first
     capture is clean. Before this fix the degradation must reproduce in
     this no-mute run too (prediction that confirms the root cause).
