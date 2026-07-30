# Task v1.8.0-1: Stable journal event references

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** none.

## Summary

Give every valid raw journal event a stable, typed reference without changing
the serialized JSONL event shape. Propagate that reference through append and
replay so every later derived layer has one provenance identity to use.

## Context you need

- `src/jarvis/journal/events.py`: `JournalEvent` and
  `JournalEventAppended`.
- `src/jarvis/journal/store.py`: `JournalReplay`, `append()`, and
  `read_session()`.
- `src/jarvis/journal/recorder.py`: the serialized background append path.
- `src/jarvis/ui/transport.py`: the existing `JournalEventAppended`
  subscriber.
- `tests/test_journal.py` and the live-feed tests in
  `tests/test_ui_transport.py`.

## Current boundary

- In scope: reference domain types, referenced replay, append-result
  propagation, and updates required by the event payload change.
- Out of scope: SQLite, FTS, transcripts, annotations, search, context
  budgeting, and model tools.

## Requirements

- Add a frozen `JournalEventRef` with:
  - `session_id`;
  - zero-based `event_position`.
- `event_position` is the ordinal among successfully parsed events in the
  immutable session log. Corrupt lines are skipped and counted exactly as
  they are today; they do not consume an event position.
- Add one typed record that binds a `JournalEventRef` to its `JournalEvent`.
- Existing logs gain references through replay. No JSONL line is rewritten
  and no new required JSON field is added.
- `JournalStore.append()` returns the reference assigned to the appended
  event.
- Repeated appends to one active session must not rescan the whole session on
  every call. Any one-time initialization required after reopening must be
  explicit and tested.
- `JournalEventAppended` carries both the reference and event. Existing UI
  behavior continues to read the event and publish exactly one live update.
- Session-id and non-negative-position validation belongs to the reference
  type, not to each consumer.
- Update `PROJECT.md` with the stable reference definition in the same
  change.

## Acceptance criteria

- [ ] Existing JSONL fixtures replay with deterministic references.
- [ ] Append returns the same reference that a fresh store replay assigns.
- [ ] Corrupt lines do not shift valid-event references between repeated
      replays.
- [ ] Multiple appends use consecutive references without repeated full
      session scans.
- [ ] `JournalEventAppended` publishes the assigned reference and preserves
      the existing event payload.
- [ ] Existing journal, fork, and live-feed behavior remains green.

## Stop conditions

- Stop if stable references require rewriting old JSONL sessions.
- Stop if append-time reference assignment cannot agree with rebuild-time
  replay after corrupt lines.
- Stop if avoiding repeated scans requires adding mutable identity data to
  raw events rather than keeping it in store state.
- Stop if the event payload change exposes a circular dependency between the
  journal store and bus event modules.

## Verification

- Focused: `python -m pytest tests/test_journal.py tests/test_ui_transport.py`
- Standard Ruff format/check for touched files.
