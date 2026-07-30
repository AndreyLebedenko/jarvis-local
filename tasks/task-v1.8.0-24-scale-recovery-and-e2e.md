# Task v1.8.0-24: Scale, recovery, and end-to-end verification

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-8-history-corpus-lifecycle.md`
- `task-v1.8.0-9-history-tool-provider.md`
- `task-v1.8.0-14-automatic-retrieval-wiring.md`
- `task-v1.8.0-17-transcript-api-ui-and-consumers.md`
- `task-v1.8.0-20-annotation-api-ui-and-search.md`
- `task-v1.8.0-22-consolidation-executor-and-control.md`
- `task-v1.8.0-23-semantic-retrieval-gate.md`

## Summary

Verify the complete history architecture under long-session, large-journal,
failure-recovery, and multi-step tool-use scenarios.

## Context you need

- all completed v1.8.0 components
- existing fake backend and MCP/tool-loop functional tests
- existing journal corruption and rebuild tests
- project performance-test conventions

## Current boundary

- In scope: cross-component tests and defects revealed within the approved
  v1.8.0 design.
- Out of scope: new product capabilities and an unapproved semantic backend.

## Requirements

- Build large synthetic journals without hardware or live Ollama.
- Verify startup sync, incremental append, deletion, and derived-corpus
  rebuild after corruption.
- Detect accidental full-session rescans on each append.
- Exercise a long conversation where an old fact is recovered through:
  - automatic retrieval;
  - an explicit history tool;
  - a transcript;
  - an annotation.
- Verify that each resulting Ollama request remains within its declared
  budget and preserves current-turn media rules.
- Exercise a multi-step tool loop under the existing shared call budget.
- Verify cancellation and restart recovery during transcription, annotation,
  and consolidation operations.
- Prove raw journal immutability across every derived operation.
- Keep timing assertions broad and platform-independent; put hardware
  performance observations in the manual handoff.

## Acceptance criteria

- [ ] The pure end-to-end scenario passes without live Ollama, screen capture,
  microphone, speakers, GPU, or network.
- [ ] Large-journal append work is bounded by the new event plus local index
  work,
  not total journal length.
- [ ] A corrupt disposable corpus rebuilds from authoritative journal data.
- [ ] No cross-component test exposes hidden content in Hidden mode or logs
  conversational text.
- [ ] Any defect fix remains inside an already approved task boundary.

## Stop conditions

- Stop if a failure reveals an architectural choice not settled by the story
  or completed task cards.
- Stop if project tooling fails for an environmental reason.
- Stop if meeting a scale target requires a broad refactor outside v1.8.0.

## Verification

- Focused scale, recovery, and end-to-end tests.
- `python -m pytest`
- Ruff checks.
