# Task v1.8.0-12: Working-context orchestration

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-11-working-context-assembler.md`
- completed v1.7.3 reasoning-prompt work

## Summary

Integrate the bounded working-context assembler into dialog orchestration and
remove the flat, unbounded message replay from live Ollama requests.

## Context you need

- `src/jarvis/app.py`
- `src/jarvis/dialog/backend.py`
- `tests/test_main.py`
- the completed v1.7.3 implementation

## Current boundary

- In scope: request construction and in-memory recent-history ownership.
- Out of scope: automatic retrieval, history tools, transcription,
  annotations, and retention.

## Requirements

- Replace the live-request use of the flat `ConversationHistory` replay with
  grouped exchanges selected by task 10 and assembled by task 11.
- Keep the append-only journal as the full session record.
- Preserve:
  - normal completed turns;
  - aborted turns and their outcome notes;
  - blank-context turns;
  - fork provenance;
  - reasoning-mode prompt selection;
  - current-turn time;
  - current-turn-only media;
  - interruption and busy-state behavior.
- Seed a fork with pinned provenance plus bounded recent exchanges rather
  than copying an unbounded flat transcript.
- Emit content-free diagnostic metrics for estimated prompt usage and each
  context category.
- Do not log retrieved or conversational text in new diagnostics.
- Keep request construction testable without live Ollama or hardware.

## Acceptance criteria

- [ ] A long session no longer causes all prior messages to be sent to Ollama.
- [ ] Recent complete exchanges remain coherent at the budget boundary.
- [ ] Existing normal, aborted, fork, time, media, and reasoning tests retain
  their behavior.
- [ ] Diagnostic metrics expose why a request fits without exposing its
  content.
- [ ] Functional tests demonstrate bounded prompt construction across many
  turns.

## Stop conditions

- Stop if v1.7.3 and v1.8.0 both need to own prompt selection.
- Stop if preserving abort or fork semantics requires changing the journal
  event model beyond task 1.

## Verification

- Focused orchestration and request-construction tests.
- `python -m pytest`
- Ruff checks.
