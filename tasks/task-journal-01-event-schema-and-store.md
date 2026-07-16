# Task journal-01: Journal event schema and JSONL store

**Status:** Planned.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`

## Summary

Create the journal's core data layer: an event schema and an append-only
per-session JSONL store with replay. Pure logic, no wiring into the app
yet.

## Context you need

- Story card sections "Layered design" and "Boundaries".
- `src/jarvis/app.py`: `ConversationHistory` / `Turn` (lines ~89-115) show
  what a turn currently carries. Do NOT modify app.py in this task.
- Project rules: UTF-8, ASCII in code/comments, `python -m pytest`.

## Boundary

- New package `src/jarvis/journal/` with `events.py` and `store.py` plus
  tests. No changes outside it (except `src/jarvis/journal/__init__.py`).
- No bus wiring, no UI, no SQLite index (later tasks).
- Binary media never goes inside JSONL - events reference media files by
  relative path only. This task does not write media files itself; it
  only stores the reference strings it is given.

## Requirements

- `events.py`: a `JournalEvent` dataclass with fields:
  - `session_id: str`, `timestamp: str` (ISO 8601 with timezone),
  - `source: str` (open set - e.g. "voice", "clipboard", "assistant";
    do not validate against a closed enum),
  - `role: str` ("user" | "assistant"),
  - `text: str` (may be empty for voice turns),
  - `media: list[str]` (relative file paths, may be empty),
  - `transcript: str | None` (always None in v1.5.0 - reserved, derived).
  - `to_json_line()` / `from_json_line()` round-trip helpers.
- `store.py`: a `JournalStore` with a root directory:
  - one JSONL file per session: `<root>/<session_id>/events.jsonl`;
    media files live in the same session directory;
  - `append(event)` - append one line, flush; must tolerate concurrent
    process restarts (append mode, never rewrite);
  - `read_session(session_id)` - replay events in order, skipping (and
    counting) corrupt lines instead of raising;
  - `list_sessions()` - session ids with first/last event timestamps,
    sorted by start time.
- Session id format: sortable timestamp prefix, e.g.
  `20260716-153000-<short-random>`.

## Acceptance criteria

- [ ] Round-trip: event -> JSON line -> event is lossless, UTF-8, one
      line per event.
- [ ] `append` then `read_session` returns events in order across
      simulated restarts (reopen store between appends in a test).
- [ ] A corrupt line in the middle of a file does not break replay of
      the rest.
- [ ] `list_sessions` ordering and timestamps are covered by tests.
- [ ] `python -m pytest` green; tests are pure (tmp_path only, no
      hardware, no network).
