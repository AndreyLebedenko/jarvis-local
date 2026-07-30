# Task v1.8.0-23: Semantic retrieval decision gate

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-7-exact-history-search.md`
- `task-v1.8.0-17-transcript-api-ui-and-consumers.md`
- `task-v1.8.0-20-annotation-api-ui-and-search.md`

## Summary

Measure exact/prefix retrieval on a fixed Russian evaluation corpus and decide
from recorded evidence whether v1.8.0 needs a semantic retrieval backend.

## Context you need

- `PROJECT.md` Russian FTS limitations
- task 7 exact-search implementation
- transcript and annotation search integration
- story acceptance criteria for graceful retrieval degradation
- the existing `.venv-mcp-qdrant` and read-only Qdrant MCP example, which are
  prior provider-path evidence only, not a selected v1.8.0 storage design

## Current boundary

- In scope: the evaluation corpus, deterministic benchmark, thresholds, and
  recorded decision.
- Out of scope: embeddings and semantic-backend implementation.

## Requirements

- Create a small fixed Russian corpus covering:
  - exact terms;
  - inflection and paraphrase;
  - distant facts;
  - transcript text;
  - annotation text;
  - distractors.
- Define relevance judgments and top-k success metrics before recording the
  result.
- Run the benchmark against the exact/prefix implementation without live
  Ollama or network access.
- Record corpus version, metrics, threshold, result, and decision in
  `PROJECT.md`.
- Keep exact/prefix retrieval as the mandatory offline fallback regardless of
  the result.
- If the threshold is met, close the gate with no semantic runtime.
- If the threshold is not met, stop and ask the owner to choose a semantic
  design; create a separate implementation task card only after that
  architectural decision.
- Do not give Qdrant a preference, change the threshold, or skip candidate
  evaluation merely because its MCP example environment already exists.

## Acceptance criteria

- [ ] The benchmark is deterministic and runnable in the pure automated
  suite.
- [ ] The threshold and relevance labels cannot be changed after seeing
      results without an explicit documented revision.
- [ ] The decision is reproducible from repository files.
- [ ] No new runtime dependency is introduced by the gate itself.
- [ ] The recorded decision distinguishes external MCP-provider evidence from
      the requirements of an integrated, rebuildable history corpus.

## Stop conditions

- Stop if two semantic approaches have non-obvious locality, resource, model,
  or storage trade-offs.
- Stop if passing the gate would require weakening the predeclared threshold
  after results are known.

## Verification

- Focused retrieval benchmark tests.
- `python -m pytest`
- Ruff checks.
