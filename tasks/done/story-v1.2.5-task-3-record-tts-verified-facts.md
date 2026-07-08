# Task: Record verified TTS facts

**Story:** `tasks/story-v1.2.5-tts-engine-foundation.md`
**Status:** Completed.
**Release:** v1.2.5
**Depends on:** `tasks/story-v1.2.5-task-2-tts-engine-spike.md`

## Summary

Update `PROJECT.md` with human-confirmed TTS timing, quality, and resource
facts before choosing the TTS migration direction.

## Current Boundary

- Documentation and decision capture only.
- Use human-reported spike output.
- Do not implement engine refactor in this task.

## Acceptance Criteria

- [ ] `PROJECT.md` records measured latency, cold load, quality notes, and
      VRAM/headroom findings.
- [ ] `PROJECT.md` records q8_0 KV-cache findings relevant to TTS headroom.
- [ ] TTS host/model direction is stated only if the measurements support it.
- [ ] Open questions remain explicit where measurements are inconclusive.
- [ ] Facts that should not be re-tested casually are marked consistently with
      existing project style.

## Verification

- Read `PROJECT.md` with `Get-Content -Raw -Encoding UTF8`.
- Run `python -m pytest` unless the human agrees to docs-only review.

## Stop Conditions

- Stop if human results are incomplete or internally inconsistent.
- Stop if measurements reveal non-obvious trade-offs with architectural
  consequences.

