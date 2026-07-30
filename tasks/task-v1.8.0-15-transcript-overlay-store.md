# Task v1.8.0-15: Transcript overlay store

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-5-derived-corpus-rebuild.md`
- `task-v1.8.0-6-history-read-api.md`
- `task-v1.8.0-8-history-corpus-lifecycle.md`

## Summary

Add a derived, editable transcript overlay for historical voice events without
rewriting the append-only journal.

## Context you need

- `src/jarvis/journal/events.py`
- the task 5 derived-corpus schema and repository
- the task 6 event-reference API
- `PROJECT.md` media payload and journal immutability facts

## Current boundary

- In scope: transcript persistence, validation, and index-update seams.
- Out of scope: Ollama calls, transport routes, UI, and fork behavior.

## Requirements

- Store transcripts by stable journal event reference.
- Preserve provenance metadata, including creation/update time, producer
  version, and whether the value was generated or user-edited.
- Enforce configured transcript size limits.
- Accept transcripts only for eligible historical voice events.
- Never mutate the raw JSONL event or overload its existing `transcript`
  field.
- Make transcript writes and derived search-index updates atomic from the
  repository caller's perspective.
- Support idempotent create, replace, read, and delete operations.
- Expose typed outcomes for missing, ineligible, conflicting, and invalid
  event references.

## Acceptance criteria

- [ ] A raw journal byte-for-byte comparison is unchanged after transcript
  edits.
- [ ] Generated and user-edited transcripts are distinguishable.
- [ ] Repeating the same write is harmless.
- [ ] Transcript replacement removes stale search text.
- [ ] Unit tests cover size limits, wrong event type, missing reference,
  update,
  delete, and transaction rollback.

## Stop conditions

- Stop if the existing raw `JournalEvent.transcript` field and the overlay
  cannot be given unambiguous precedence rules.
- Stop if atomic search updates require coupling the raw journal to SQLite.

## Verification

- Focused transcript repository and derived-index unit tests.
- `python -m pytest`
- Ruff checks.
