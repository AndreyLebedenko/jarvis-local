# Task v1.8.0-5: Derived history corpus schema and rebuild

**Status:** Completed.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-1.

## Summary

Create the rebuildable SQLite history corpus and populate its normalized event
projection from existing raw JSONL sessions. This task does not add FTS or
live incremental updates.

## Context you need

- `src/jarvis/journal/store.py` and task 1's referenced replay contract.
- `src/jarvis/journal/search.py`: current disposable `index.db`.
- `tests/test_journal.py` and `tests/test_journal_search.py`.
- `PROJECT.md` append-only and rebuildable-derived-layer decisions.

## Current boundary

- In scope: schema ownership/versioning, event projection, full rebuild,
  read-only inspection needed by tests, and legacy-index disposition.
- Out of scope: FTS, query API, append-time updates, transcripts, annotations,
  tools, UI, and context assembly.

## Requirements

- Add one history-corpus repository under `src/jarvis/journal/`.
- Store one row per valid referenced raw event with the fields needed by later
  reads and filters: reference, timestamp/sort value, role, source, raw text,
  media metadata, and JSON metadata.
- Preserve source JSON values without type erasure.
- The corpus DB is derived and lives outside session directories.
- Use an explicit schema version. An unknown newer schema fails clearly; an
  old disposable search schema may be dropped/rebuilt rather than migrated.
- `rebuild()` creates a complete replacement from `JournalStore` and does not
  mutate raw sessions.
- A failed rebuild must not leave a partially valid database presented as
  complete. Use a transaction or replace-on-success strategy.
- Corrupt raw lines remain counted by replay and absent from the corpus.
- No FTS virtual table is introduced in this task.

## Acceptance criteria

- [x] Rebuild projects all valid user, assistant, and system events with exact
      references and metadata.
- [x] A second rebuild is deterministic.
- [x] Corrupt lines do not abort other events or sessions.
- [x] Failure rolls back or leaves the prior valid corpus intact.
- [x] Raw JSONL and media bytes are unchanged.
- [x] Unknown schema versions fail explicitly.

## Stop conditions

- Stop if normalized projection requires changing raw `JournalEvent`.
- Stop if SQLite cannot preserve the required JSON values without lossy
  conversion.
- Stop if safe replacement conflicts with Windows file/connection behavior.
- Stop if corpus ownership would create a dependency from `JournalStore` onto
  SQLite.

## Verification

- New focused corpus tests using temporary raw sessions and databases.
- Existing journal store/search tests.
- Ruff checks.

## Review notes

- Legacy `index.db` disposition: the existing disposable FTS index remains
  owned by `JournalSearchIndex` in `src/jarvis/journal/search.py`. The new
  normalized corpus uses a separate `history_corpus.db`; task v1.8.0-5 does
  not migrate, delete, or rebuild `index.db`.
