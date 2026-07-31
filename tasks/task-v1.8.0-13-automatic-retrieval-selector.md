# Task v1.8.0-13: Automatic retrieval selector

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-4-context-budget-core.md`
- `task-v1.8.0-6-history-read-api.md`
- `task-v1.8.0-7-exact-history-search.md`
- `task-v1.8.0-7a-exact-retrieval-quality-gate.md`
- any conditional semantic/hybrid backend task inserted after task 8.

## Summary

Implement the pure selection policy that converts retrieval candidates from
the final approved history-domain search surface into a small, relevant,
non-duplicated set of past journal passages.

## Context you need

- the task 4 budget types
- the task 6 read-result types
- the task 7 search-result types
- task 7a's recorded exact-only or semantic/hybrid decision
- any conditional semantic/hybrid candidate-result contract approved before
  this card
- `PROJECT.md` notes about Russian FTS behavior

## Current boundary

- In scope: deterministic query construction, candidate ranking, filtering,
  deduplication, and budget selection.
- Out of scope: database access, retrieval backend implementation, and
  orchestration changes.

## Requirements

- Define typed inputs and outputs for automatic retrieval.
- Construct retrieval candidate requests deterministically from the current
  user text. When task 7a approves exact-only retrieval, this means exact and
  prefix queries; when a semantic/hybrid backend is approved, this means its
  final local candidate API.
- Apply configurable limits for candidate count, accepted count, relevance,
  and token budget.
- Deduplicate overlapping hits and passages already present in the selected
  recent context.
- Preserve stable event references and enough surrounding context to make a
  hit understandable.
- Prefer fewer complete, higher-value passages over many truncated snippets.
- Skip weak or empty results instead of filling the budget mechanically.
- Keep source framing separate from conversational message roles.

## Acceptance criteria

- [ ] Identical inputs produce identical selected passages.
- [ ] Current/recent content is not injected a second time.
- [ ] Low-relevance matches are omitted.
- [ ] Passage selection never exceeds its assigned retrieval budget.
- [ ] Tests cover Russian prefix fallback, overlap, duplicate recent content,
      relevance ties, empty input, and insufficient budget.
- [ ] If a semantic/hybrid backend was approved before this card, tests cover
      the backend-neutral candidate contract rather than hard-coding FTS-only
      assumptions.

## Stop conditions

- Stop if task 7 does not expose a stable relevance order.
- Stop if the approved retrieval surface does not expose a stable candidate
  contract for selector input.
- Stop if useful query construction requires an additional generative model
  call; that is outside this task and the v1.8.0 default path.

## Verification

- Focused selector unit tests.
- `python -m pytest`
- Ruff checks.
