# Task v1.8.0-13: Pure recent-history selection policy

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-4.

## Summary

Implement pure logic for selecting a bounded recent tail of complete exchanges
for one working context.

## Current boundary

In scope: complete-exchange grouping, oldest-drop-first selection, token
budget use, blank-context behavior as input state, and tests.

Out of scope: retrieval I/O, orchestration wiring, tool calls, transcripts,
annotations, and prompt assembly.

## Requirements

- Select whole recent turns without splitting messages.
- Preserve current system outcome notes for interrupted and failed turns.
- Respect `minimum_recent_exchanges` when possible without overflowing the
  configured budget.
- Drop oldest complete exchanges first.
- Treat current-turn media as out of scope for retained history.
- Return explicit budget and truncation metadata for later observability.

## Acceptance criteria

- [ ] Empty, tiny, exact-fit, and over-budget inputs are deterministic.
- [ ] Interrupted and failed-turn notes keep their existing semantics.
- [ ] Blank context clears the candidate tail before selection.
- [ ] No retrieval or journal I/O is introduced.

## Stop conditions

- Stop if existing `ConversationHistory` cannot expose complete exchanges
  without changing orchestration first.
- Stop if preserving interruption semantics requires splitting turns.

## Verification

- Focused pure policy tests.
- `python -m pytest`
- Ruff checks.
