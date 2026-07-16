# Task journal-03: Derived SQLite FTS5 search index

**Status:** Completed.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`
**Depends on:** task-journal-01. (Independent of task-journal-02.)

## Summary

A search index over journal events: SQLite FTS5, fully derived from the
JSONL logs, rebuildable at any time. Query API: full-text over assistant
answers plus date-range filtering. Pure logic, no UI, no transport.

## Context you need

- Story card: search scope is assistant text answers + dates; FTS5 comes
  from stdlib sqlite3 (zero new dependencies); Russian stemming is a
  known accepted limitation (exact/prefix forms only).
- `src/jarvis/journal/store.py` from task-journal-01 (`list_sessions`,
  `read_session`).

## Boundary

- New module `src/jarvis/journal/search.py` plus tests. No changes
  outside `src/jarvis/journal/` and tests.
- Index only assistant-role event text in FTS. User text and transcripts
  are NOT indexed in v1.5.0 (transcripts do not exist yet; widening the
  index is a later decision).
- The index file lives inside the journal root (e.g. `<root>/index.db`)
  and is disposable: deleting it must never lose data.

## Requirements

- `JournalSearchIndex` with:
  - `rebuild()` - drop and rebuild from the store;
  - `update_session(session_id)` - (re)index one session incrementally;
  - `search(query, date_from=None, date_to=None, limit=...)` returning
    hits with session_id, timestamp, event position, and a text snippet;
  - a date-only mode: empty query + date range lists matching sessions.
- Use FTS5 with prefix matching enabled so partial word forms match
  (mitigates the Russian stemming limitation).
- Dates are compared on event timestamps (ISO 8601 from task-journal-01);
  a date-only `date_to` must include that whole day.

## Acceptance criteria

- [x] Rebuild from a store fixture with several sessions produces correct
      hits; deleting index.db and rebuilding gives identical results.
- [x] Search matches assistant text only (a user-text-only token is not
      found).
- [x] Date filtering: from/to bounds inclusive, whole-day semantics
      covered by tests, including a cross-midnight session.
- [x] Russian text round-trips: a Cyrillic query finds a Cyrillic answer
      (exact and prefix form).
- [x] `python -m pytest` green; tmp_path only, no new dependencies in
      `requirements.txt`.
