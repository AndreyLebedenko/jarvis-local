# Task v1.8.0-21: Annotation overlay store

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-9.

## Summary

Persist bounded, source-grounded session or event annotations as derived
overlay data.

## Current boundary

In scope: annotation schema, source references, size caps, read/write/delete,
session deletion, and repository tests.

Out of scope: model generation, UI controls, retrieval projection integration,
and consolidation.

## Requirements

- Store annotations outside raw JSONL.
- Link every annotation to a session or explicit event range.
- Enforce size, count, and metadata limits.
- Preserve author/source/status metadata.
- Support deletion and rebuild health semantics.
- Never treat annotations as replacements for source events.

## Acceptance criteria

- [ ] Raw journal bytes are unchanged by annotation writes.
- [ ] Invalid references and oversize annotations are rejected.
- [ ] Session deletion removes annotations.
- [ ] Reads expose source references and metadata.

## Stop conditions

- Stop if annotations cannot stay visibly tied to source material.
- Stop if storing annotations requires changing raw event schema.

## Verification

- Focused annotation repository tests.
- Existing journal/corpus tests.
- `python -m pytest`
- Ruff checks.
