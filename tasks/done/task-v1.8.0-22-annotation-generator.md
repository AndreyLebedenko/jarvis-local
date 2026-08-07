# Task v1.8.0-22: Historical annotation generator

**Status:** Completed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-21.

## Summary

Add explicit, source-grounded, non-dialog local Ollama annotation generation.

## Current boundary

In scope: generation service, prompt construction, source grounding,
concurrency, size bounds, status reporting, and manual handoff.

Out of scope: automatic scheduler, UI, retrieval projection integration, and
consolidation execution.

## Requirements

- Generate annotations only through explicit user/UI command.
- Use bounded source ranges read through the history API.
- Prompt the model to summarize only cited source material.
- Store output as editable annotation overlay data.
- Keep model/configuration metadata.
- Avoid competing unpredictably with live dialog.
- Make failures retryable and auditable.

## Acceptance criteria

- [x] Pure tests cover prompt construction and source bounding.
- [x] Generated annotations include source references.
- [x] Oversize source ranges and outputs are rejected.
- [x] Manual handoff command is provided for live Ollama verification.

## Stop conditions

- Stop if source grounding cannot be enforced structurally.
- Stop if annotation generation creates unpredictable live-turn resource use.

## Verification

- Pure service tests with fake backend.
- Manual local Ollama handoff.
- `python -m pytest`
- Ruff checks.
