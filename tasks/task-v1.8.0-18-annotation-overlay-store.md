# Task v1.8.0-18: Annotation overlay store

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-5-derived-corpus-rebuild.md`
- `task-v1.8.0-6-history-read-api.md`
- `task-v1.8.0-8-history-corpus-lifecycle.md`

## Summary

Add a derived, editable session-annotation overlay with explicit source
references and bounded storage.

## Context you need

- the task 5 derived-corpus schema and repository
- the task 6 range and event-reference API
- existing journal session metadata and UI models

## Current boundary

- In scope: annotation persistence and validation.
- Out of scope: Ollama calls, annotation search indexing, and API/UI controls.

## Requirements

- Store zero or more bounded annotations per session.
- Preserve source event/range references, creation/update time, producer
  version, and generated-versus-user-edited state.
- Enforce configured per-annotation and per-session size/count limits.
- Validate that all source references belong to the annotated session.
- Never rewrite or replace raw journal events or transcript overlays.
- Support idempotent create, replace, list, and delete operations.
- Make invalid, stale, and conflicting updates explicit typed outcomes.
- Include schema versioning and deterministic rebuild behavior.

## Acceptance criteria

- [ ] Annotation provenance survives restart and derived-corpus reopen.
- [ ] Invalid cross-session source references are rejected.
- [ ] User edits cannot be mistaken for generated text.
- [ ] Rebuild preserves raw history while safely discarding/recreating only
      data declared rebuildable by the schema contract.
- [ ] Unit tests cover all limits, provenance validation, conflicts, and
  rollback.

## Stop conditions

- Stop if generated annotations cannot be separated from user-authored
  durable data during a corpus rebuild.
- Stop if the product requirements do not define whether user edits are
  rebuildable or authoritative.

## Verification

- Focused annotation repository and schema migration/rebuild tests.
- `python -m pytest`
- Ruff checks.
