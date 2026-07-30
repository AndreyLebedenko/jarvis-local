# Task v1.8.0-3: Context token-budget spike

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** completed v1.7.3 and task v1.8.0-2.

## Summary

Measure how Jarvis can estimate Gemma4 prompt tokens before dispatch without
loading a second model-sized runtime. Record one approved estimator and
explicit safety margins for the later context-budget implementation.

## Context you need

- `PROJECT.md` verified Ollama model, `num_ctx`, KV-cache, and hardware facts.
- `src/jarvis/dialog/backend.py`: payload construction and
  `prompt_eval_count`.
- `src/jarvis/dialog/tool_presentation.py`: repeated tool-loop requests and
  tool declarations.
- `src/jarvis/app.py`: current system/history/time/user message order.
- The completed v1.7.3 effective reasoning-prompt result and its final source
  paths. Do not assume a module layout from the proposed v1.7.3 cards.

## Current boundary

- In scope: a reproducible measurement script, pure payload/estimator tests,
  human-run instructions, results, and the architecture decision.
- Out of scope: production context trimming, config fields, history search,
  embeddings, and changing `num_ctx`.

## Requirements

- Compare viable local approaches:
  - an exact tokenizer available without duplicating the loaded model;
  - a lightweight compatible tokenizer;
  - a conservative measured estimator using message text and fixed overhead.
- Include Russian prose, English/code-like text, system plus memory prompt
  material, tool declarations, tool results, and mixed short/long turns.
- Compare every estimate with Ollama's returned `prompt_eval_count`.
- Measure both the initial request and a tool follow-up request.
- The human runs every live Ollama case. Automated tests cover only payload
  construction, result parsing, and pure estimator math.
- Record in `PROJECT.md`:
  - the selected approach;
  - maximum observed underestimation;
  - the required safety margin;
  - exact default reserve values and config field names for task 4;
  - rejected approaches and why.
- Do not change production request behavior in this spike.

## Acceptance criteria

- [ ] The handoff script produces machine-readable estimates and real
      `prompt_eval_count` values for every case.
- [ ] The owner reports the live output.
- [ ] One approach is approved with a safety margin that never underestimated
      the measured cases after margin application.
- [ ] `PROJECT.md` contains enough exact decisions for task 4 to implement
      without choosing new defaults.

## Stop conditions

- Stop if no candidate can bound Russian/tool prompts conservatively without a
  second model-sized runtime.
- Stop if Ollama reports inconsistent counts for identical payloads in a way
  that invalidates the comparison.
- Stop if the selected estimator would require an unapproved runtime
  dependency or model download.
- Stop after preparing the handoff until the human returns the live results.

## Verification

- Pure tests for estimator/payload logic.
- Human-run command and captured output recorded in the card outcome.
