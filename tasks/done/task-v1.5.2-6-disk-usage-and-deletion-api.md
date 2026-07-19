# Task v1.5.2-6: Journal disk usage and deletion API

**Status:** Completed.
**Story:** `tasks/done/story-v1.5.2-journal-ux-pack.md`
**Depends on:** nothing in this story; independent of tasks 1-5.

## Summary

Give the journal store the ability to report disk usage (total and
per-session) and delete a whole session, keep the FTS index consistent,
and expose both through the authenticated transport. Store and
transport only; the UI flow is task-v1.5.2-7.

## Context you need

- `src/jarvis/journal/store.py`: `JournalStore` layout - per-session
  JSONL log plus media files beside it; `list_sessions()`.
- `src/jarvis/journal/search.py`: `JournalSearchIndex.rebuild()` /
  `update_session()`; the index is rebuildable from raw logs, and the
  schema currently has no per-session delete - decide between a
  targeted delete of the session's rows and a full rebuild, and record
  why (stop if neither stays cheap for large journals).
- `src/jarvis/ui/transport.py`: journal endpoint auth and Hidden
  gating; `_resolve_journal_media_path()` shows the traversal-guard
  pattern session ids must also pass through.
- Cross-cutting rules 6 and 8 (`tasks/roadmap-v1.5.1-v1.7.md`): manual,
  user-confirmed, whole-session deletion only; no automatic deletion;
  this is an interim disk valve, not retention policy.

## Boundary

- Whole sessions only; no per-event or media-only deletion.
- The active (currently recording) session must not be deletable, and
  the layering is fixed: `JournalStore` knows only files - it deletes
  any existing session safely; the active-session guard lives in the
  transport/API layer, which is told the recorder's current session id
  (`JournalRecorder.session_id`). The store must not grow a dependency
  on the recorder or runtime state.
- No confirmation UI here - the transport contract carries the intent
  (explicit DELETE request), the human-facing confirmation is
  task-v1.5.2-7.
- No scheduling, no thresholds, no auto-cleanup of any kind.

## Requirements

- `JournalStore` gains usage reporting: per-session byte size (log plus
  media) and the journal total, plus a `delete_session(session_id)`
  that removes the session log and its media files.
- Session ids are validated against the store's real session set;
  crafted ids cannot escape the journal root (tested, mirroring the
  media traversal tests).
- Deletion updates the FTS index so deleted sessions stop appearing in
  search results.
- Transport endpoints: usage query (GET) and session deletion (DELETE
  or POST - match the existing routing style), both token-authenticated
  and suppressed in Hidden mode exactly like existing journal
  endpoints.
- The transport layer rejects deletion of the recorder's current
  session with a structured error; the store itself has no notion of
  "active".
- Deletion of a nonexistent session returns a structured not-found
  error, not a 500.

## Acceptance criteria

- [x] Store tests cover usage numbers (sessions with and without
      media), deletion removing log and media, unknown-session error,
      and traversal-safe id validation.
- [x] Search tests prove a deleted session's hits disappear while other
      sessions' hits survive.
- [x] Transport tests cover auth, Hidden suppression, successful
      usage/delete round trips, active-session rejection, and the
      other structured error cases.
- [x] No UI behavior changes.
- [x] `python -m pytest` and Ruff checks are green.
