# Task v1.8.0-10: Pure recent-history selection policy

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-4.

## Summary

Define a pure atomic representation of completed conversation exchanges and
select the newest verbatim suffix that fits the recent-history allocation.
Do not change `Orchestrator` yet.

## Context you need

- `ConversationHistory`, `Turn`, normal completion, and
  `record_aborted_turn()` in `src/jarvis/app.py`.
- Fork seeding in `src/jarvis/journal/fork.py`.
- Task 4 budget types and estimator.
- Tests around history, interruption, failure, fork, and blank context in
  `tests/test_main.py`.

## Current boundary

- In scope: pure working-history types, atomic exchange grouping, suffix
  selection, pinned session provenance, and tests.
- Out of scope: message assembly, automatic retrieval, orchestration,
  journals, tools, backend calls, and replacement of `ConversationHistory`.

## Requirements

- Represent one completed user exchange as an atomic unit containing:
  - the user message;
  - optional assistant text;
  - optional interrupted/failed system note.
- Represent session-level provenance separately from completed exchanges so a
  fork/new-context marker is not accidentally treated as an answer turn.
- Select a contiguous newest suffix; never create a middle hole.
- Drop oldest whole exchanges first. Never keep an assistant/outcome note
  after dropping its user message.
- Preserve message text and roles verbatim.
- Enforce the configured minimum-recent-exchange rule only while it fits the
  mandatory fixed/reserve budget.
- If the newest single exchange cannot fit, return a typed over-budget result;
  do not split or silently omit the current conversation.
- The policy depends only on immutable inputs and the pure estimator.

## Acceptance criteria

- [ ] Normal, empty-answer, interrupted, failed, forked, and blank-context
      shapes group deterministically.
- [ ] Oldest complete exchanges are removed first.
- [ ] No selected output contains orphan assistant or outcome messages.
- [ ] Exact-fit and newest-exchange-overflow cases are explicit.
- [ ] Selection is deterministic and has 100% non-trivial branch coverage.

## Stop conditions

- Stop if current flat history cannot be mapped to atomic exchanges without
  ambiguous role patterns.
- Stop if preserving existing interrupted-turn semantics requires special
  text parsing.
- Stop if pinned provenance and recent-history budgets acquire circular
  ownership.

## Verification

- New pure recent-history policy tests.
- No live Ollama, journal, UI, or hardware tests.
- Ruff checks.
