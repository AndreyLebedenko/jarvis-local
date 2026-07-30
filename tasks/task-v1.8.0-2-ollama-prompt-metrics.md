# Task v1.8.0-2: Ollama prompt-token metrics

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** none.

## Summary

Expose Ollama's `prompt_eval_count` through the existing typed completion
metrics so later context-budget work can be measured instead of inferred.

## Context you need

- `src/jarvis/dialog/backend.py`: `LatencyMetrics`, `parse_metrics()`, and
  zero-metric completion paths.
- `src/jarvis/dialog/tool_presentation.py`: its own zero-metric fallback and
  final `ResponseComplete`.
- `src/jarvis/core/debug_transcript.py`: already records
  `prompt_eval_count`.
- `tests/test_backend.py`, `tests/test_tool_presentation.py`,
  `tests/test_main.py`, `tests/test_tts.py`, and `tests/test_module_health.py`.

## Current boundary

- In scope: the typed metric, parsing, zero/default behavior, and focused
  consumers/tests.
- Out of scope: working-context selection, new UI panels, persistent analytics,
  token estimation, and changes to Ollama payloads.

## Requirements

- Add `prompt_eval_count` to `LatencyMetrics`.
- Parse it from Ollama's terminal `done:true` chunk.
- Missing metrics and streams ending without `done:true` report zero rather
  than inventing a value.
- Keep existing constructors readable; a default value is acceptable if it
  avoids unrelated fixture churn without hiding real parsed data.
- Native and prompt tool-loop completions preserve the final request's metric
  exactly as they preserve the existing latency metrics.
- Do not add prompt content to logs. This metric is a count only.

## Acceptance criteria

- [ ] A terminal Ollama chunk produces the expected prompt-token count.
- [ ] Missing and incomplete-stream cases produce zero.
- [ ] Tool-loop final completion carries the parsed count.
- [ ] Existing response, TTS, health, and debug-transcript behavior is
      unchanged.

## Stop conditions

- Stop if different Ollama request paths give `prompt_eval_count` incompatible
  meanings that cannot share one field.
- Stop if exposing the count requires logging model input content.
- Stop if the change requires altering `ResponseComplete` ordering or turn
  completion semantics.

## Verification

- Focused:
  `python -m pytest tests/test_backend.py tests/test_tool_presentation.py`
- Run affected main/TTS/module-health tests and Ruff checks.
