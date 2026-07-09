# Story v1.2.9 Task 3: Bilingual TTS router

Status: Backlog.

## Summary

Wire a bilingual `TtsEngine` implementation that dispatches Russian segments
to Silero and English segments to Piper according to the configured language
routes.

## Boundary

In scope:

- Add an engine composition layer behind `TtsEngine`.
- Route `language="ru"` and `language="en"` to configured child engines.
- Keep `TtsOutput` responsible for buffering and ordered playback only.
- Preserve `OrderedPlayback` semantics when two engines synthesize at different
  speeds.
- Wire the configured engine from `main.py` or the existing app construction
  boundary.

Out of scope:

- Changing charset segmentation.
- Adding languages beyond `ru` and `en`.
- Adding UI controls.
- Changing conversation history or display text.

## Acceptance Criteria

- `ru` segments synthesize through the configured Russian engine.
- `en` segments synthesize through the configured English engine.
- Unsupported language hints fail clearly or use a documented fallback covered
  by tests.
- Later English segments cannot play before earlier Russian segments.
- Existing Silero-only default behavior remains available.
- Tests cover the configured `ru -> Silero`, `en -> Piper` route using fake
  engines.

## Notes

The implementation should reuse v1.2.8 charset segmentation. Do not re-open
the rejected model-authored language tag path.
