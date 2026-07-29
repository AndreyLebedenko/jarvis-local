# Task v1.8.0-14: Automatic retrieval wiring

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-8-history-corpus-lifecycle.md`
- `task-v1.8.0-11-working-context-assembler.md`
- `task-v1.8.0-12-working-context-orchestration.md`
- `task-v1.8.0-13-automatic-retrieval-selector.md`

## Summary

Add bounded, automatic journal retrieval to the start of a dialog turn and
feed its selected passages into the working-context assembler.

## Context you need

- `src/jarvis/app.py`
- the task 8 corpus lifecycle owner
- the task 11 assembler
- the task 13 selector
- interruption and busy-state tests in `tests/test_main.py`

## Current boundary

- In scope: automatic retrieval and working-context integration.
- Out of scope: generative query rewriting, semantic embeddings, UI,
  transcription, and annotations.

## Requirements

- Retrieve candidates before final request assembly for eligible text turns.
- Use only local derived-corpus reads and the deterministic task 13 policy.
- Do not add an Ollama request solely to decide what to retrieve.
- Fall back to recent context when the derived corpus is absent, rebuilding,
  corrupt, or temporarily unavailable.
- Keep cancellation, interruption, and busy-state behavior race-safe.
- Do not write new journal events for retrieved passages.
- Keep explicit history tools available independently of automatic
  retrieval.
- Record only content-free retrieval counts, estimated tokens, and timing.

## Acceptance criteria

- [ ] An old relevant fact can enter a bounded prompt without replaying the
  session.
- [ ] Retrieval failure does not prevent a normal recent-context response.
- [ ] Retrieved material is delimited as historical data.
- [ ] No duplicate journal or conversation events are produced.
- [ ] Functional tests cover a relevant hit, no hit, degraded index,
  cancellation,
  and a turn that later uses an explicit history tool.

## Stop conditions

- Stop if corpus reads can block the event loop without a defined async
  boundary.
- Stop if degraded retrieval changes the user's ability to continue a
  conversation.

## Verification

- Focused automatic-retrieval functional tests.
- `python -m pytest`
- Ruff checks.
