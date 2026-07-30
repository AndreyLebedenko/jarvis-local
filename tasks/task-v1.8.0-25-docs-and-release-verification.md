# Task v1.8.0-25: Documentation and release verification

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- all mandatory v1.8.0 task cards
- any conditional semantic-retrieval implementation card created by task 23

## Summary

Document the completed architecture and user controls, run the full automated
suite, and prepare the exact human verification handoff for v1.8.0.

## Context you need

- all completed v1.8.0 task cards and implementation
- `PROJECT.md`
- `README.md`
- configuration examples and validation docs
- roadmap and story card
- the historical journal-retention bug report, if present

## Current boundary

- In scope: documentation, examples, task status, and verification handoffs.
- Out of scope: runtime behavior and feature expansion.

## Requirements

- Update `PROJECT.md` with the final:
  - authoritative versus derived data model;
  - event-reference contract;
  - context-budget algorithm and measured margin;
  - retrieval behavior and semantic-gate decision;
  - transcription, annotation, and consolidation invariants;
  - Ollama and locality implications.
- Document every `[history]` setting and default in the configuration example.
- Update user documentation for:
  - bounded working context;
  - automatic and explicit history retrieval;
  - transcript and annotation controls;
  - consolidation preview, execution, and recovery;
  - Hidden-mode behavior.
- Reconcile the roadmap, story, and task-card statuses.
- Close or update the journal-retention bug report with the implemented
  boundary and verification evidence.
- Prepare exact human-run checks for live Ollama prompt metrics,
  transcription, annotation quality, media consolidation, latency, and host
  resource use.
- Run every project-defined automated check and leave the repository green.

## Acceptance criteria

- [ ] A coder can reconstruct the final architecture and invariants from
  `PROJECT.md` without reading the implementation first.
- [ ] Every configuration key used by code is documented with its default and
  validation rules.
- [ ] User docs distinguish unlimited durable history from bounded per-request
  context.
- [ ] Manual commands state prerequisites, expected output, and what the human
  must report.
- [ ] Roadmap, story, tasks, and bug reports do not contradict one another.

## Stop conditions

- Stop if implementation behavior differs from the approved story or recorded
  architectural decisions.
- Stop if any automated check fails outside this documentation task's scope.
- Stop until the human reports required hardware/live-Ollama results; do not
  mark the story completed without them.

## Verification

- `python -m pytest`
- Ruff checks.
- `tools/graphify.ps1 update` when the graph exists.
- Hand the human the complete manual verification checklist.
