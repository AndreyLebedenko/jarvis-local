# Task v1.8.0-8: Local hybrid retrieval design spike

**Status:** Completed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** completed tasks v1.8.0-1 through v1.8.0-7.

## Decision (owner-ratified 2026-08-01)

Selected: pymorphy3 morphology baseline + `multilingual-e5-large-instruct`
(Ollama) primary semantic backend + `embeddinggemma:300m` config-swappable
fallback, fused with a per-query relative gate (not an absolute cosine
threshold). Full evidence, measured numbers, rejected alternatives, and the
per-turn cost budget are recorded in `PROJECT.md` under the v1.8.0 hybrid
retrieval spike section. Ratified thresholds live in
`tests/retrieval_benchmark/corpus.py` as `RATIFIED_THRESHOLDS`. The fixed
benchmark and the deterministic/human-run measurement tools live in
`tests/retrieval_benchmark/`.

## Summary

Choose the local semantic or hybrid retrieval architecture before any
model-facing history consumer is wired.

This is a decision spike, not implementation. It exists because exact/prefix
FTS is the lexical fallback and provenance aid, not the memory engine.

## Current boundary

In scope: compare candidate local retrieval backends, passage shape,
embedding/model options, persistence, lifecycle, resource use, quality gates,
and owner decision.

Out of scope: production vector storage, tool provider, automatic retrieval,
working context, transcripts, annotations, consolidation, and UI.

## Requirements

- Measure a morphology-aware lexical baseline first: lemmatized or stemmed FTS
  applied at index and query time, with no model and no per-turn inference.
  Candidate morphology backends are a pymorphy3 or pymorphy-compatible
  analyzer, a Snowball stemmer, or another measured local morphology backend.
  Do not adopt pymorphy2: its `inspect.getargspec` use is incompatible with
  the project's Python 3.11 runtime. Record the baseline's standalone benchmark
  result as the reference the embedding layer must beat.
- Verify install and runtime compatibility of the chosen morphology backend on
  Python 3.11 before selecting it, including import, a smoke lemmatization, and
  `requirements.txt` impact.
- Evaluate at least two local semantic/hybrid options, including whether a
  no-server embedded store is sufficient and whether Qdrant is justified. An
  embedding or vector layer is justified only by its incremental benchmark gain
  over the lexical baseline, principally on paraphrase and synonym cases, not
  by word-form recall the lemmatizer already delivers.
- Allow "lemmatized-lexical plus a light semantic reranker" as an approved
  outcome if it clears the threshold; a full vector store is a candidate
  outcome, not the assumed one. A reranker that needs a model forward pass on
  the live path counts as semantic hot-path work under the same per-turn
  latency and VRAM budget as query embedding, unless it is measured to run
  offline, at index time, or within a bounded CPU cost over a small candidate
  set.
- Treat the existing `.venv-mcp-qdrant` and read-only Qdrant MCP example as
  provider-path evidence only, not as backend selection evidence.
- Define passage granularity and how each passage maps back to
  `JournalEventRef` or bounded event ranges.
- Define how lexical FTS and semantic candidates combine with filters,
  ranking, deduplication, and read-back.
- Define installation and configuration requirements for the embedding model
  and index store.
- Estimate disk, RAM, VRAM, startup, rebuild, and append costs on the owner's
  Windows host.
- Measure the per-turn query cost on the live path separately from indexing:
  the time to turn one user query into semantic candidates, including query
  embedding. Decide whether the embedding model is kept resident (VRAM cost,
  contends with Ollama) or loaded per query (latency cost), and record the
  trade-off.
- Define the per-turn automatic-retrieval time budget and the rule that a turn
  exceeding it falls back to lexical-only retrieval rather than delaying
  generation.
- Define deterministic pure tests and human-run measurement commands.
- Define the fixed early hybrid retrieval quality benchmark and thresholds
  before implementation sees results.
- Record the selected design and rejected alternatives in `PROJECT.md`.

## Acceptance criteria

Closure: all criteria are met by the decision recorded in `PROJECT.md`
(v1.8.0 hybrid retrieval spike section), the benchmark and tools in
`tests/retrieval_benchmark/`, and the requirements pushed into cards 9, 10,
and 11. Per-item:

- [x] The owner-approved backend is named explicitly (pymorphy3 + e5-large-
      instruct primary + embeddinggemma fallback + relative gate).
- [x] The morphology-aware lexical baseline has a recorded standalone
      benchmark result, and any embedding layer's gain is stated as an
      increment over it (B0/B1/B2 in `PROJECT.md`).
- [x] The chosen morphology backend is verified to install and import on
      Python 3.11, with its `requirements.txt` impact recorded (pymorphy3;
      spike deps not added to `requirements.txt` until implementation).
- [x] Exact/prefix retrieval remains the offline literal fallback.
- [x] Every semantic candidate has stable source provenance (benchmark maps
      passages to `JournalEventRef`; read-back required by cards 10/11).
- [x] The design covers rebuild, append, deletion, and unavailable-backend
      behavior (pushed into cards 9 and 10).
- [x] The per-turn live query cost is measured, and the resident-versus-per-
      query embedding trade-off and per-turn fallback budget are recorded
      (Ollama keeps the model resident; cold-start and over-budget fall back
      to lexical-only).
- [x] Quality thresholds and labels are predeclared (`RATIFIED_THRESHOLDS`).
- [x] Resource and locality trade-offs are explicit (latency/VRAM per model in
      `PROJECT.md`; all backends local).

## Stop conditions

- Stop if backend candidates have non-obvious quality, dependency,
  persistence, or host-resource trade-offs requiring owner choice.
- Stop if a candidate requires network access at runtime.
- Stop if a candidate cannot preserve deletion and rebuild semantics.
- Stop if the semantic layer would expose vector hits as facts without typed
  read-back.

## Verification

- Spike notes in `PROJECT.md`.
- Any small pure probes needed for candidate inspection.
- Human-run commands for host-resource measurements when needed.
