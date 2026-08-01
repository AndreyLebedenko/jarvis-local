# Task v1.8.0-18: Transcript overlay store

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-9.

## Summary

Persist editable derived transcripts without rewriting raw journal events.

## Current boundary

In scope: transcript schema, provenance, size limits, edit history boundary,
read API, rebuild behavior, and deletion lifecycle.

Out of scope: transcription generation, UI controls, retrieval projection
integration, annotations, and consolidation.

## Requirements

- Store transcripts as derived overlay data keyed by source event reference.
- Preserve raw `JournalEvent.transcript` values without rewriting JSONL.
- Enforce transcript size and text validity limits.
- Support read, upsert, delete, and session delete operations.
- Make transcript source/status explicit.
- Participate in projection lifecycle and rebuild health.

## Acceptance criteria

- [ ] Raw JSONL remains byte-identical after transcript edits.
- [ ] Transcript reads return source references and status.
- [ ] Session deletion removes transcript rows.
- [ ] Invalid references and over-limit text are rejected explicitly.

## Stop conditions

- Stop if transcript identity cannot map to legacy events.
- Stop if preserving edits requires mutating raw journal lines.

## Verification

- Focused transcript repository tests.
- Existing journal/corpus tests.
- `python -m pytest`
- Ruff checks.
