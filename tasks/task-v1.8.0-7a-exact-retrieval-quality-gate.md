# Task v1.8.0-7a: Exact retrieval quality gate

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-7.

## Summary

Measure exact/prefix retrieval on a fixed Russian evaluation corpus at the
first point where it is testable, before history tools, automatic retrieval,
and working-context wiring depend on its signal.

This task decides whether v1.8.0 stays exact-only or needs an owner-approved
local semantic or hybrid retrieval backend. It does not implement embeddings.

## Context you need

- `PROJECT.md` Russian FTS limitations.
- Task 5 corpus schema, task 6 read API, and task 7 exact-search
  implementation.
- Story decisions 10 and 11 about retrieval gating and derived-layer
  lifecycle ownership.
- The existing `.venv-mcp-qdrant` and read-only Qdrant MCP example, which are
  provider-path evidence only, not a selected integrated backend.

## Current boundary

- In scope: evaluation corpus, deterministic benchmark, fixed thresholds,
  relevance labels, recorded metrics, and the exact-only versus semantic
  decision.
- Out of scope: embeddings, vector storage, semantic backend implementation,
  automatic retrieval policy, model tools, transcripts, annotations, and
  context assembly.

## Requirements

- Create a small fixed Russian corpus covering:
  - exact terms;
  - inflection and prefix variation;
  - paraphrase;
  - exact names, dates, identifiers, and numbers;
  - temporal and session filtering;
  - distractors.
- Define relevance judgments, top-k success metrics, recall threshold, and
  irrelevant-result threshold before recording benchmark output.
- Run the benchmark against the exact/prefix implementation without live
  Ollama, embeddings, network access, or hardware.
- Record corpus version, labels, metrics, thresholds, result, and decision in
  `PROJECT.md`.
- Keep exact/prefix retrieval as the mandatory offline fallback regardless of
  the result.
- If exact retrieval meets the threshold, close the gate with no semantic
  runtime dependency.
- If exact retrieval misses the threshold, stop and ask the owner to choose a
  semantic or hybrid design. The selected design receives a conditional task
  card in the story slot after task 8 and before retrieval consumers.
- Do not prefer Qdrant, change thresholds, or skip candidate evaluation merely
  because a Qdrant MCP example environment already exists.

## Acceptance criteria

- [ ] The benchmark is deterministic and runnable in the pure automated
      suite.
- [ ] Thresholds and relevance labels cannot be changed after seeing results
      without an explicit documented revision.
- [ ] The decision is reproducible from repository files.
- [ ] No new runtime dependency is introduced by the gate itself.
- [ ] The recorded decision distinguishes external MCP-provider evidence from
      the requirements of an integrated, rebuildable history corpus.
- [ ] Downstream retrieval consumers can tell whether they should depend on
      exact-only search or wait for a conditional semantic/hybrid backend.

## Stop conditions

- Stop if two semantic approaches have non-obvious locality, resource, model,
  or storage trade-offs.
- Stop if passing the gate would require weakening the predeclared threshold
  after results are known.
- Stop if exact-search ranking is too unstable to make the benchmark
  reproducible.

## Verification

- Focused retrieval benchmark tests.
- `python -m pytest`
- Ruff checks.
