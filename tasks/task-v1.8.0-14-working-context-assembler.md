# Task v1.8.0-14: Working-context assembler

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-11 and v1.8.0-13.

## Summary

Compose one bounded Ollama request from prompt layers, selected recent turns,
retrieved passages, time context, current request, and current media.

## Current boundary

In scope: pure assembly, ordering, delimiter format for historical passages,
budget accounting, truncation reporting, and tests.

Out of scope: orchestration wiring, actual retrieval I/O, tool execution,
transcription, annotations, and UI.

## Requirements

- Preserve the effective system prompt from the reasoning-prompt story.
- Place recent tail before automatically retrieved historical passages.
- Present retrieved history as delimited source data with reference, role,
  source, timestamp, and passage text.
- Keep historical text from becoming system instructions.
- Preserve current-turn time context ordering.
- Attach current-turn media only to the current user request.
- Reserve configured room for reasoning/generation, tools, tool results, and
  forced-final pass.
- Return prompt-budget metadata for observability.

## Acceptance criteria

- [ ] Assembly order is deterministic and tested.
- [ ] Historical passages are clearly source-framed.
- [ ] Current-turn media is never copied into retained history.
- [ ] Over-budget inputs fail before dispatch or drop permitted history only.
- [ ] Fork, blank-context, interruption, and time-context contracts remain
      representable.

## Stop conditions

- Stop if the assembler cannot preserve existing reasoning-prompt order.
- Stop if budget enforcement cannot protect final-generation headroom.
- Stop if safe source framing requires changing tool result semantics.

## Verification

- Focused assembler tests.
- Existing context-budget tests.
- `python -m pytest`
- Ruff checks.
