# Task v1.8.0-10: Semantic passage and index store

**Status:** Completed.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-8 and v1.8.0-9.

## Summary

Implement the selected local semantic projection as rebuildable,
source-grounded passages and index data.

The task-8 decision (recorded in `PROJECT.md`) selects
`multilingual-e5-large-instruct` (via Ollama) as the primary embedding backend
and `embeddinggemma:300m` as a config-swappable latency fallback. All
per-backend parameters live in a `[history.semantic]` config block, not in
code: Ollama model id, query/passage prefixes, relative-gate `separation` and
`top_ratio`, and expected dimension. The projection code is embedding-model
agnostic; switching backends is a config change plus a rebuild, never a code
change.

## Current boundary

In scope: passage schema, embedding/index storage, rebuild, append update,
delete projection, unavailable state, health metadata, and repository tests.

Out of scope: hybrid ranking policy, model-facing tools, automatic retrieval,
working context, transcripts, annotations, and UI controls.

## Requirements

- Store semantic passages as derived data with stable source references.
- Keep passage text source-grounded; do not store generated summaries as the
  only retrievable text.
- Persist embedding/index metadata needed to reject stale model/configuration
  mismatches explicitly. The stamp includes the Ollama model id, embedding
  dimension, and prompt-prefix configuration used to build the index.
- Read all per-backend parameters from the `[history.semantic]` config block;
  do not hard-code the model, prefixes, or gate parameters.
- Rebuild from the history corpus and selected effective text surface.
- Support incremental append and session deletion through task 9 lifecycle.
- Provide a typed semantic candidate query API with scores and references.
- Make unavailable or unbuilt semantic state explicit and non-mutating.
- Keep exact/prefix FTS independent and usable when semantic retrieval is
  disabled or unavailable.

## Acceptance criteria

- [x] Rebuild creates deterministic passage references for a fixed corpus.
- [x] Append updates only the new event's relevant passages.
- [x] Deletion removes the session's semantic data.
- [x] Model/config mismatch is detected clearly.
- [x] Candidate queries return references, scores, and no authoritative facts.
- [x] Reads do not scan raw JSONL during normal operation.

## Stop conditions

- Stop if passage identity cannot survive rebuild deterministically enough for
  audit and tests.
- Stop if the selected backend cannot represent deletion without orphaned
  vectors.
- Stop if embedding work competes unpredictably with live dialog resources.

## Verification

- Focused semantic projection tests with deterministic fakes or fixtures.
- Existing journal corpus/search tests.
- `python -m pytest`
- Ruff checks.
