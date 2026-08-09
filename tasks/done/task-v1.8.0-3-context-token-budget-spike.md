# Task v1.8.0-3: Context token-budget spike

**Status:** Completed.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
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

- [x] The handoff script produces machine-readable estimates and real
      `prompt_eval_count` values for every case.
- [x] The owner reports the live output.
- [x] One approach is approved with a safety margin that never underestimated
      the measured cases after margin application.
- [x] `PROJECT.md` contains enough exact decisions for task 4 to implement
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

## Human-run handoff

Prepared script:
`python -m manual.manual_check_context_token_budget`

It writes machine-readable results to
`manual_check_context_token_budget_out/results.json`. Return that file or its
complete JSON content for the decision pass. The script sends each identical
payload twice and stops if `prompt_eval_count` changes between the two runs.
It covers:

- Russian prose, English/code-like text, and a mixed long history;
- system plus explicit curated-memory-shaped prompt material;
- native tool initial and follow-up requests;
- prompt-strategy tool initial and follow-up requests;
- prompt material hashes and sizes without writing prompt content.

Candidate boundary before the live run:

- Ollama's `prompt_eval_count` is the exact reference but arrives only after
  the complete request has been accepted and evaluated, so it cannot protect
  that same request before dispatch.
- An optional existing local SentencePiece `tokenizer.model` can be measured
  with `--sentencepiece-model-path <path>`. The legacy
  `--tokenizer-model <path>` spelling remains accepted. Both options require a
  filesystem path, not an Ollama model name, and the script never downloads
  tokenizer data.
  This counts canonical message/tool material, not Ollama's rendered chat
  template, so compatibility must be measured rather than assumed exact.
- `conservative_utf8` is the provisional no-dependency estimator:
  `ceil(canonical_utf8_bytes / 2) + 32 + 12 * messages + 24 * tools`.
  Its safety margin and suitability are undecided until the owner returns the
  output.

Pure verification command:
`python -m pytest manual/tests/test_manual_check_context_token_budget.py`

## Owner-returned live result

The owner ran the script without an external tokenizer and returned
`manual_check_context_token_budget_out/results-gemma4-12B-unified.json` on
2026-07-31. The run used Ollama 0.32.5, `gemma4:12b-it-qat`, and
`num_ctx = 65536`.

- All eight case payloads returned the same `prompt_eval_count` in both runs.
- Observed prompt counts ranged from 472 to 2441 tokens.
- `conservative_utf8` never underestimated a case. Maximum observed
  underestimation was 0 tokens, minimum headroom was 876 tokens, and maximum
  headroom was 4663 tokens.
- The narrowest observed estimate-to-reference ratio was 1940 / 721, or
  approximately 2.69.
- Passing `gemma4:12b-it-qat` to the optional tokenizer argument failed
  because it is an Ollama model name, not a filesystem path to a standalone
  SentencePiece model file. The script now rejects that input before any live
  request with a direct path-specific error instead of a low-level traceback.

## Approved decision

Select the no-dependency `conservative_utf8` estimator. Its unrounded input is
the canonical UTF-8 message/tool material used by the spike, and its estimate
is:

`ceil(utf8_bytes / 2) + 32 + 12 * message_count + 24 * tool_count`

Apply one additional global `1024`-token safety margin after estimating the
complete assembled prompt. The margin is applied once, not once per message or
category. The measured maximum underestimation remains 0 after margin, while
the minimum measured total headroom becomes 1900 tokens.

The owner approved this decision on 2026-07-31.

Approve these exact task 4 `[history]` fields and defaults:

```toml
[history]
prompt_capacity_tokens = 49152
recent_history_max_tokens = 24576
automatic_retrieval_max_tokens = 8192
tool_result_reserve_tokens = 8192
reasoning_generation_reserve_tokens = 16384
estimator_safety_margin_tokens = 1024
minimum_recent_exchanges = 1
```

`prompt_capacity_tokens` is input capacity and excludes the separate
reasoning/generation reserve. Their defaults sum to the verified
`backend.num_ctx = 65536`. Recent-history and automatic-retrieval values are
optional maxima, not mandatory reservations; fixed prompt input can reduce
their realized allocations. The tool/result and reasoning/generation values
are mandatory reserves and cannot be borrowed by history or retrieval.

Reject the other candidates for production:

- `prompt_eval_count` remains the exact post-dispatch feedback signal, but it
  is unavailable before the request it measures and therefore cannot enforce
  that request's limit.
- A standalone compatible SentencePiece model is not part of the repository
  or the owner-returned input. An Ollama model name does not expose one through
  this script, and even a supplied file would count the canonical proxy rather
  than Ollama's rendered Gemma4 chat template. Selecting it would add an asset
  and runtime dependency without establishing exactness.
