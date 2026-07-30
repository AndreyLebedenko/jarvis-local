# Task v1.8.0-21: Historical consolidation planner

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-15-transcript-overlay-store.md`
- `task-v1.8.0-18-annotation-overlay-store.md`
- `task-v1.8.0-4-context-budget-core.md`

## Summary

Implement a pure planner that decides which inactive-session media may be
consolidated and lists the required operations in a safe dependency order.

## Context you need

- journal media event types and storage layout
- transcript and annotation overlay state models
- `[history]` configuration from task 4
- `tasks/bug_reports/journal-retention-not-enforced.md`, if present

## Current boundary

- In scope: pure consolidation planning and validation.
- Out of scope: filesystem writes, journal rewrites, Ollama calls, and
  background scheduling.

## Requirements

- Define near-history and far-history eligibility from explicit configuration
  and session timestamps.
- Always reject the active session.
- Plan operations in dependency order:
  - produce a transcript when required;
  - produce annotations when required;
  - create an approved reduced image representation when configured;
  - remove eligible historical audio only after transcript verification.
- Preserve original near-history media.
- Represent blocked reasons explicitly, including missing transcript,
  missing annotation, active session, corrupt media, and unsupported type.
- Produce deterministic, idempotent plans from the same inventory.
- Include expected source and destination identities so execution can detect
  stale plans.
- Do not infer storage policy from free disk space or run automatically.

## Acceptance criteria

- [ ] No plan can delete audio before a verified effective transcript exists.
- [ ] No plan can alter media in the active session or near-history window.
- [ ] Replanning after partial completion lists only remaining safe
  operations.
- [ ] Tests cover all age boundaries, missing prerequisites, mixed media,
  unsupported media, stale inventory, and disabled consolidation.

## Stop conditions

- Stop if the story and current configuration do not define one unambiguous
  near/far-history boundary.
- Stop if image consolidation requires a lossy policy whose acceptable quality
  or dimensions are unspecified.

## Verification

- Focused consolidation planner unit and property-style boundary tests.
- `python -m pytest`
- Ruff checks.
