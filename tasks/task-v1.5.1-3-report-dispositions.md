# Task v1.5.1-3: Dispositions for the non-code v1.5.0 reports

**Status:** Ready.
**Story:** `tasks/story-v1.5.1-stabilization.md`

## Summary

Documentation only. Record the planning outcomes of 2026-07-18 in the two
open reports that need no code in this release, so neither carries a stale
"undecided" status.

## Context you need

- `tasks/bug_reports/2026-07-17-journal-retention-policy.md`
- `tasks/bug_reports/2026-07-17-distorted-voice-in-journal-recording.md`
- `tasks/roadmap-v1.5.1-v1.7.md`: the v1.7.0 consolidation section
  (near/far journal design) and cross-cutting rule 8 (no audio
  auto-deletion before its transcript exists).

## Boundary

- Edits to the two report files only (plus, if needed, a one-line
  cross-reference from `PROJECT.md`'s existing retention note to the
  roadmap). No code, no config, no cleanup behavior.

## Requirements

- Retention report: add a disposition section stating the owner's
  decision - retention is the v1.7.0 consolidation pipeline (near log
  with full media; far log with transcripts, compressed images, and
  model-written annotations; explicit trigger). The report stays open
  until that pipeline ships; what closes here is the question "which
  policy", not the implementation. Until then the only interim relief is
  v1.5.2's disk-usage visibility and manual deletion; automatic deletion
  remains forbidden.
- Distorted-voice report: add the recurrence protocol - on the next
  occurrence, preserve the wav; compare its waveform against a clean
  sibling for clipping, dropouts, or resampling artifacts; check
  correlation with concurrent TTS/sound-cue playback or model inference
  load; note the microphone device type and connection (USB, Bluetooth,
  built-in) in effect, cross-referencing task-v1.5.1-4's device matrix
  results if available.

## Acceptance criteria

- [ ] Both reports carry their disposition/protocol sections with the
      2026-07-18 decision date and a pointer to the roadmap.
- [ ] No other files change except an optional one-line `PROJECT.md`
      cross-reference.
- [ ] `python -m pytest` still green (docs-only change; run as the
      standard gate).
