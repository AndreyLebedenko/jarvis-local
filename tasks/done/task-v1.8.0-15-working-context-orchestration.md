# Task v1.8.0-15: Working-context orchestration

**Status:** Completed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-14.

## Summary

Replace unbounded live replay with the bounded working-context assembler in
the real dialog path.

## Current boundary

In scope: orchestration wiring, metrics propagation, existing dialog
semantics, fake-backend tests, and removal of unbounded normal prompt replay.

Out of scope: automatic retrieval I/O, history tools, transcripts,
annotations, and UI.

## Requirements

- Use the assembler for normal backend requests.
- Preserve blank context, fork seed, interruption, failed-turn notes,
  reasoning-mode prompts, time context, and current media behavior.
- Keep journal recording append-only.
- Expose prompt-budget and truncation metadata through existing observability
  paths where available.
- Do not dynamically alter `backend.num_ctx`.

## Acceptance criteria

- [ ] A long synthetic history no longer grows normal prompt size linearly.
- [ ] Existing dialog behavior tests stay green.
- [ ] Fork and blank-context contracts are unchanged.
- [ ] Interrupted and failed turns are still recorded correctly.
- [ ] Current media remains current-turn only.

## Stop conditions

- Stop if replacing replay changes journal ordering.
- Stop if the tool loop cannot receive assembled history without semantic
  ambiguity.
- Stop if preserving fork behavior requires rewriting old journal events.

## Verification

- Focused orchestration tests with fake backend.
- Existing `tests/test_main.py` and dialog tests.
- `python -m pytest`
- Ruff checks.
