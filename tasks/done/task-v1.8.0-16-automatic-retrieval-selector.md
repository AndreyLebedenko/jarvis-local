# Task v1.8.0-16: Automatic retrieval selector

**Status:** Completed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-4, v1.8.0-11, and v1.8.0-13.

## Summary

Implement pure selection logic that chooses a small, relevant,
non-duplicated set of historical passages from hybrid retrieval candidates.

## Current boundary

In scope: deterministic request construction, ranking, thresholding,
deduplication, recent-context overlap removal, and token-budget selection.

Out of scope: database/index I/O, backend implementation, orchestration
wiring, tools, and prompt assembly.

## Requirements

- Define typed inputs and outputs for automatic retrieval selection.
- Construct retrieval requests deterministically from current user text and
  selected recent context.
- Consume the approved hybrid candidate contract, not FTS-specific details.
- Operate correctly on a lexical-only candidate set, since automatic retrieval
  degrades to lexical when the semantic path is unavailable or over budget;
  a missing semantic score is a normal input, not an error.
- Apply configurable limits for candidates, accepted passages, relevance, and
  token budget.
- Deduplicate overlapping hits and passages already present in recent context.
- Prefer fewer complete, high-value passages over many truncated snippets.
- Skip weak or empty results instead of filling the budget mechanically.
- Keep source framing separate from conversational roles.

## Acceptance criteria

- [ ] Identical inputs produce identical selected passages.
- [ ] Current/recent content is not injected a second time.
- [ ] Low-relevance matches are omitted.
- [ ] Selection never exceeds its assigned retrieval budget.
- [ ] Tests cover Russian paraphrase, prefix fallback, exact identifier
      fallback, lexical-only candidates with no semantic score, overlap, ties,
      empty input, and insufficient budget.

## Stop conditions

- Stop if approved hybrid retrieval lacks a stable candidate contract.
- Stop if useful query construction requires an additional generative call.
- Stop if weak-match filtering cannot be made deterministic.

## Verification

- Focused selector unit tests.
- `python -m pytest`
- Ruff checks.
