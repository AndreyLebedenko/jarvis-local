# Task v1.8.0-11: Working-context assembler

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-4-context-budget-core.md`
- `task-v1.8.0-10-recent-history-policy.md`
- completed v1.7.3 reasoning-prompt work

## Summary

Build a pure component that assembles one bounded Ollama request from the
effective prompt, pinned context, recent exchanges, retrieved passages, the
current time, and the current user turn.

## Context you need

- `src/jarvis/app.py`
- `src/jarvis/dialog/thinking_mode.py`, the current reasoning-level owner
- the completed v1.7.3 reasoning-prompt story, task cards, and resulting
  source files; no dedicated reasoning package exists today, so its location
  must not be assumed
- `PROJECT.md` sections covering current-turn time and media handling

## Current boundary

- In scope: pure message assembly, budget reporting, and unit tests.
- Out of scope: replacing `ConversationHistory`, journal queries, Ollama calls,
  and orchestrator control flow.

## Requirements

- Define typed inputs for:
  - the effective prompt snapshot;
  - pinned provenance messages;
  - selected recent exchanges;
  - bounded retrieved passages with source references;
  - the current time message;
  - the current user message.
- Produce Ollama-compatible messages and a structured budget breakdown.
- Preserve this order:
  - effective prompt;
  - pinned provenance and recent history;
  - clearly delimited retrieved history;
  - current-turn time;
  - current user input.
- Treat retrieved history as quoted data, not as instructions.
- Apply the task 4 budget policy and preserve its reserved capacity for tool
  use and response generation.
- Keep current-turn media outside persisted history and attach it only to the
  current user message.
- Return a typed error if fixed content alone exceeds the available budget.
  Do not silently truncate the effective prompt or current user message.
- Keep the component deterministic and free of I/O.

## Acceptance criteria

- [ ] The assembler never returns messages above its declared input budget.
- [ ] Each input category has an observable token estimate in the result.
- [ ] Retrieved passages retain stable journal references.
- [ ] Prompt, time, and current-media semantics remain unchanged.
- [ ] Unit tests cover exact fit, one-token overflow, no history, no retrieval,
  oversized fixed content, and mixed text/media input.

## Stop conditions

- Stop if v1.7.3 does not expose one unambiguous effective prompt snapshot.
- Stop if the completed v1.7.3 layout differs from the paths or seams assumed
  by this card; update the card from the landed code before implementation.
- Stop if fitting fixed content requires changing the settled prompt or
  current-turn time semantics.

## Verification

- Focused assembler unit tests.
- `python -m pytest`
- Ruff checks.
