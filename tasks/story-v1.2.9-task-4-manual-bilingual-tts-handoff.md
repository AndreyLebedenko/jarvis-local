# Story v1.2.9 Task 4: Manual bilingual TTS handoff

Status: Backlog.

## Summary

Prepare and record the human-run verification for production bilingual TTS:
Russian speech through Silero, English speech through Piper, preserving segment
order.

## Boundary

In scope:

- Update or reuse manual check scripts for the configured production route.
- Provide exact commands for the human to run.
- Record the human result in `PROJECT.md`.
- Mark v1.2.9 task cards complete only after the manual result is accepted.

Out of scope:

- Agent-run speaker/GPU/live TTS checks.
- Additional model comparisons.
- Graphify refresh unless explicitly requested as part of the handoff.

## Acceptance Criteria

- The handoff command exercises mixed Russian/English text through the actual
  configured runtime path.
- The output shows which engine handled each segment.
- The human confirms speech quality and ordering are acceptable.
- `PROJECT.md` records the chosen route and any model paths/constraints that
  matter architecturally.
- `python -m pytest` passes before handoff.

## Notes

The spike result already chose `silero_ru_piper_en`; this task verifies that
the production wiring, not only the spike harness, behaves the same way.
