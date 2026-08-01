# Task v1.8.0-11: Hybrid retrieval domain API and quality gate

**Status:** Completed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-8 through v1.8.0-10.

## Summary

Expose one domain retrieval API that combines semantic and lexical candidates,
hydrates selected references through typed reads, and passes the fixed Russian
quality benchmark before downstream consumers are built.

## Current boundary

In scope: backend-neutral query/result types, hybrid ranking, filters,
deduplication, read-back, thresholds, benchmark corpus, metrics, and recorded
decision.

Out of scope: tool provider, automatic retrieval selector, context assembly,
transcripts, annotations, and UI.

## Requirements

- Define one `HistoryRetrievalService` or equivalent domain API.
- Accept query text plus supported session/time/role/source filters.
- Combine semantic candidates with lexical FTS candidates.
- Gate semantic candidates with a per-query relative gate, not a fixed absolute
  cosine threshold. Task 8 measured that absolute thresholds do not transfer
  across models (e5 needed 0.8 where bge/gemma needed 0.5) and collapse
  precision; the relative gate rejects a query whose top score does not stand
  out from the median and keeps candidates within a ratio of the top, restoring
  precision and staying silent on queries the lexical side already answers. The
  gate parameters (`separation`, `top_ratio`) are per-backend config.
- Preserve exact lookup strength for names, dates, identifiers, and numbers.
- Hydrate selected candidates through typed event/range reads before returning
  model-facing text.
- Fix one backend-neutral candidate/result contract so the selector does not
  guess: each candidate exposes source mode (semantic, lexical, or both), an
  optional semantic score (absent in lexical-only mode), a lexical score or
  rank, and a combined rank. Absence of a semantic score is a valid,
  documented state, not an error.
- Return provenance, score metadata, source mode, truncation, and count data.
- Run the fixed task-8 benchmark (`tests/retrieval_benchmark/`) against
  `RATIFIED_THRESHOLDS`. The pure suite uses the deterministic concept fixture;
  the real-model validation against the primary (e5) and fallback
  (embeddinggemma) backends is a human-run handoff via
  `measure_semantic`, and both models' results are recorded.
- Record corpus version, labels, thresholds, metrics, result, and decision in
  `PROJECT.md`, including the morphology-aware lexical baseline row and the
  measured increment the semantic layer adds over it, so the embedding cost
  stays auditable against its benefit.
- Keep exact/prefix retrieval as mandatory offline fallback.

## Acceptance criteria

- [x] The benchmark is deterministic and runnable in the pure suite.
- [x] Hybrid retrieval meets `RATIFIED_THRESHOLDS` on the fixture in the pure
      suite, and the primary backend (e5) meets them in the recorded human-run
      measurement.
- [x] The fallback backend (embeddinggemma) preserves lexical and morphology
      recall and keeps the distractor false-positive rate at 0.0; its lower
      semantic recall is recorded as a deliberate latency-for-quality trade and
      is not gated on `RATIFIED_THRESHOLDS`.
- [x] Semantic gating is relative, not a fixed absolute threshold, and the
      distractor false-positive rate stays 0.0 for both backends.
- [x] Exact identifiers still work when semantic retrieval is unavailable.
- [x] Paraphrase and Russian word-form cases are covered.
- [x] Filters compose with both semantic and lexical candidates.
- [x] The candidate contract exposes source mode, optional semantic score,
      lexical score/rank, and combined rank, and is stable for lexical-only
      results.
- [x] The result is reproducible from repository files.

## Stop conditions

- Stop if passing requires weakening thresholds after seeing results.
- Stop if ranking is too unstable for reproducible tests.
- Stop if useful hybrid retrieval requires a generative model call.
- Stop if a vector hit cannot be hydrated into source-grounded text.

## Verification

- Focused hybrid retrieval benchmark tests.
- Existing corpus/search/read tests.
- `python -m pytest`
- Ruff checks.
