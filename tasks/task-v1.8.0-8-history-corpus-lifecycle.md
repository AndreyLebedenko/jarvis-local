# Task v1.8.0-8: History corpus lifecycle and incremental indexing

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-1 and v1.8.0-5 through v1.8.0-7.

## Summary

Move corpus startup, append-time indexing, and deletion consistency out of
the UI transport into one history-domain lifecycle owner.

## Context you need

- `JournalRecorder._append_event()` and `JournalEventAppended`.
- `UiTransportServer.start()`, `_on_journal_event_appended()`,
  `_rebuild_journal_index()`, `_update_journal_index()`, and session delete.
- `build_app()`, `App`, and `wire()` in `src/jarvis/app.py`.
- `tests/test_ui_transport.py`, `tests/test_main.py`, and journal-search tests.

## Current boundary

- In scope: one lifecycle service/coordinator, startup synchronization,
  incremental event projection/FTS update, deletion orchestration, app
  wiring, and removal of index ownership from UI.
- Out of scope: transcripts, annotations, tools, context assembly,
  consolidation, and UI redesign.

## Requirements

- Introduce one history-domain lifecycle owner constructed by `build_app()`.
- At startup it validates or rebuilds the derived corpus independently of
  whether Status Console is enabled.
- Subscribe to `JournalEventAppended` and insert exactly that referenced event
  transactionally. Do not delete/re-index the whole session.
- Current-session events become searchable after their append completes.
- Provide one delete-session operation that:
  - enforces the existing active-session guard at the command boundary;
  - removes raw session data and every derived row;
  - reports failure honestly if consistency cannot be guaranteed.
- `UiTransportServer` calls the history service for reads/deletion and keeps
  only UI push/rendering responsibilities.
- Hidden mode still suppresses HTTP/UI visibility; it does not control
  whether the local corpus remains internally consistent.
- Shutdown waits for in-flight incremental writes using an explicit
  lifecycle seam.

## Acceptance criteria

- [ ] Journal indexing works when no Status Console is created.
- [ ] One appended event causes one incremental corpus update.
- [ ] UI live feed still emits exactly one event.
- [ ] Current-session search does not rebuild the whole session.
- [ ] Session deletion removes raw and derived data through one owner.
- [ ] Startup rebuild and shutdown ordering are deterministic and tested.
- [ ] No UI class owns a search-index mutation method afterward.

## Stop conditions

- Stop if one atomic deletion cannot span raw files and SQLite without a
  recoverable transaction protocol.
- Stop if bus ordering can expose a referenced event before raw append
  completion.
- Stop if app startup requires blocking the event loop on an unbounded rebuild
  without an explicit readiness state.
- Stop if extracting ownership reveals a circular dependency between app,
  journal, and UI modules.

## Verification

- Focused journal, transport, and app-wiring tests.
- A pure test proving append count remains linear across a long synthetic
  session.
- Ruff checks.
