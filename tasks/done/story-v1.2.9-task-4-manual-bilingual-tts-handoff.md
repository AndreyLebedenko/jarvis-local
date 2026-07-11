# Story v1.2.9 Task 4: Manual bilingual TTS handoff

Status: Completed.

Result: human ran `manual/manual_check_bilingual_tts_production.py`
(production wiring: load_settings -> build_tts_engine -> TtsOutput) on
2026-07-10. Per-unit output confirmed ru -> silero and en -> piper
(en_US-ryan-low), ordering and quality accepted. The first run exposed
one defect - short Russian connectives ("Для", "без") were carried into
Piper units by v1.2.8's connective rule and spelled out letter by letter;
fixed by gating the carry on all routes sharing one engine
(SpeechUnitBuffer.carry_connectives), re-run confirmed correct.

This confirms production for the tested configuration. It does not constrain
the routing schema: Silero and Piper may each be configured for either
supported language when paired with a compatible model.

## Summary

Prepare and record the human-run verification for one production bilingual
TTS configuration: Russian speech through Silero and English speech through
Piper, preserving segment order.

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

The spike result selected `silero_ru_piper_en` for this handoff; this task
verifies that the production wiring, not only the spike harness, behaves the
same way. It does not make that route mandatory.
