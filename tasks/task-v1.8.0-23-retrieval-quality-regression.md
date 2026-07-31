# Task v1.8.0-23: Retrieval quality regression

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-7a-exact-retrieval-quality-gate.md`
- `task-v1.8.0-17-transcript-api-ui-and-consumers.md`
- `task-v1.8.0-20-annotation-api-ui-and-search.md`
- any conditional semantic/hybrid backend task created after task 7a.

## Summary

Rerun the fixed Russian retrieval-quality benchmark after transcripts and
annotations join the searchable corpus, and confirm that the implemented
retrieval surface still satisfies the story's quality decision.

This task is a late regression/audit gate. The first semantic/no-semantic
decision belongs to task 7a, before downstream retrieval consumers are wired.

## Context you need

- `PROJECT.md` retrieval-quality decision from task 7a.
- Task 7 exact-search implementation.
- Any conditional semantic/hybrid backend selected after task 7a.
- Transcript and annotation search integration from tasks 17 and 20.
- Story acceptance criteria for graceful retrieval degradation.

## Current boundary

- In scope: extending or rerunning the existing benchmark against the final
  searchable text surface, recording metrics, and stopping the release if the
  final corpus contradicts the earlier retrieval-quality decision.
- Out of scope: selecting the first semantic backend, adding embeddings,
  changing automatic retrieval wiring, changing thresholds after seeing
  results, or introducing a new runtime dependency.

## Requirements

- Reuse the task 7a benchmark corpus, thresholds, relevance labels, and metric
  definitions unless an explicit documented revision is approved before
  seeing results.
- Add transcript and annotation cases to the benchmark only as new labeled
  slices; do not alter the original raw-text cases to hide regressions.
- Run the benchmark without live Ollama, network access, or hardware.
- Record final corpus version, implemented retrieval mode, metrics, threshold,
  result, and release decision in `PROJECT.md`.
- Confirm exact/prefix retrieval remains the mandatory offline fallback when
  the optional semantic path is absent or unavailable.
- If the final retrieval surface fails the recorded threshold, stop before
  scale/release verification and ask for an architectural decision. Do not
  patch selector or wiring behavior opportunistically in this task.

## Acceptance criteria

- [ ] The benchmark remains deterministic and runnable in the pure automated
      suite.
- [ ] Raw-text quality labels from task 7a are preserved.
- [ ] Transcript and annotation cases are measured as explicit additional
      slices.
- [ ] The final retrieval decision is reproducible from repository files.
- [ ] No new runtime dependency is introduced by this regression task.
- [ ] Any semantic backend evidence is tied to integrated derived-corpus
      lifecycle behavior, not to the older external MCP-provider example.

## Stop conditions

- Stop if transcript or annotation integration changes the benchmark meaning
  rather than merely expanding its searchable text surface.
- Stop if failing the regression would require weakening thresholds after
  results are known.
- Stop if fixing a retrieval-quality failure would require changing lifecycle,
  selector, or wiring ownership that was already settled by earlier cards.

## Verification

- Focused retrieval benchmark regression tests.
- `python -m pytest`
- Ruff checks.
