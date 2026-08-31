# Task v1.9.1-3: Spoken-derivative locator index + projection lifecycle

**Status:** Not started.
**Story:** `tasks/story-v1.9.1-provenance-aware-indexing.md`.
**Depends on:** task-v1.9.1-1 (descriptor vocabulary). Independent of task 2 in
code, but opened after it per the story's one-at-a-time order.
**Executor:** Sonnet 5 High. This card is storage and projection ONLY. It adds
a locator index and keeps it in sync; it exposes no query surface, no UI, no
model output. If you find yourself writing a search/query method, a UI change,
or a `search_history` change, you have crossed into task 4 - stop.

## Summary

Add a lexical, locator-only FTS surface over `metadata.spoken_derivative`,
physically separate from the canonical `history_corpus_event_fts`, inside the
same `history_corpus.db`. Wire it into the exact projection lifecycle the
canonical corpus already has: full rebuild, incremental per-event projection,
per-session update, and per-session delete. The canonical FTS must be
byte-unchanged by this addition.

## Why this exists

The mode-3 spoken derivative is stored in `event.metadata["spoken_derivative"]`
and indexed nowhere, so a user cannot find a turn by a phrase they only heard.
This card builds the index that task 4 will query. It is split from the query
half deliberately (story segmentation) so no single card owns both a schema/
lifecycle and a query/hydration/UI path.

## Required reading before implementing

- `src/jarvis/journal/corpus.py` in full, especially:
  - `_create_schema`, `_create_fts_schema`, `_ensure_schema` - how the canonical
    FTS is created and how additive schema is guarded without a version bump.
  - `_insert_record` - where an event is projected, and the existing guard
    `if event.role in {"user", "assistant"} and effective_text.strip()`.
  - `_delete_event_projection`, `_delete_session_projection`,
    `update_session_projection`, `project_event`, `rebuild`.
  - `metadata_json` column - the derivative is already stored here; the locator
    index reads it from the record's `event.metadata`, no new journal read.
- `src/jarvis/journal/recorder.py` around `spoken_derivative` /
  `spoken_derivative_interrupted` - the exact metadata keys and when they are
  present.
- `src/jarvis/journal/provenance.py` (task 1) - the `SPOKEN_DERIVATIVE`
  descriptor helper, used to tag rows conceptually (the store need not persist
  the descriptor; see the story's computed-at-read decision).

## What to build

1. **A second FTS5 table** (proposed `history_corpus_derivative_fts`) in the
   same DB, created alongside the canonical FTS in `_create_fts_schema` (or a
   sibling `_create_derivative_fts_schema` called from the same places). Columns
   mirror what a locator hit needs to resolve its owner: `session_id`,
   `event_position`, `timestamp`, `timestamp_sort` (UNINDEXED), and the indexed
   `text` = the derivative string. Use the same tokenizer/prefix settings as the
   canonical FTS so query behavior is consistent. It must be a *separate table*:
   a locator phrase must never be matchable through the canonical
   `history_corpus_event_fts MATCH` (story stop condition).
2. **Projection on insert.** In `_insert_record`, after the canonical insert,
   if `event.role == "assistant"` and `event.metadata` contains a non-empty
   `spoken_derivative` string, insert a row into the derivative FTS keyed to the
   owning event ref. Do not touch the canonical insert's guard or columns. An
   assistant event with no derivative inserts nothing into the locator table
   (the common case - modes 1 and 2).
3. **Delete/update parity.** Extend `_delete_event_projection` and
   `_delete_session_projection` to also clear the derivative FTS for the same
   keys, so `project_event`, `update_session_projection`,
   `delete_session_projection`, and `rebuild` all keep the two tables coherent.
   Every place that deletes from the canonical FTS must delete from the
   derivative FTS with the same predicate.
4. **Schema guard, no version bump.** Create the derivative table through the
   same additive `_ensure_schema` path used for the canonical FTS
   (`IF NOT EXISTS`), so an existing DB gains the table without a
   `CURRENT_HISTORY_CORPUS_SCHEMA_VERSION` change (story decision). If you
   conclude a version bump is unavoidable, that is a stop-and-confirm
   (section 0.3) - do not migrate silently.

## Explicitly out of scope

- No query/search method over the derivative table (task 4).
- No UI, no `JournalSearchIndex` change, no `search_history` change.
- No hydration of canonical text, no result types (task 4).
- No change to canonical FTS columns, guard, tokenizer, or output.
- No change to mode-3 generation or `recorder.py` write path - this card reads
  metadata that is already written.
- No semantic/embedding index (story boundary).

## Tests (pure logic; project each fixture through the repository and inspect)

- Projecting an assistant record whose metadata has a non-empty
  `spoken_derivative` inserts exactly one derivative-FTS row keyed to that
  event; the canonical FTS row is exactly as before (assert the canonical
  table's contents are unchanged by the presence of the derivative).
- An assistant record with no `spoken_derivative` (mode 1/2), and any user
  record, insert zero derivative rows.
- `rebuild` populates the derivative table from a store containing mixed
  mode-1/2/3 assistant events.
- `update_session_projection` and `project_event` re-project the derivative
  row (delete-then-insert) without duplicating it.
- `delete_session_projection` and `_delete_event_projection` remove the
  derivative rows for the target keys and leave other sessions' rows intact.
- A phrase present only in a derivative does NOT match a canonical
  `history_corpus_event_fts` query (guards the physical-separation stop
  condition) - assert at the table level, since no query API exists yet.
- An empty-string or whitespace-only `spoken_derivative` inserts nothing
  (mirror the canonical `effective_text.strip()` guard).

## Acceptance criteria

- [ ] A separate `*_derivative_fts` table exists in `history_corpus.db`, created
      via the additive `_ensure_schema` path with no corpus schema-version bump.
- [ ] Assistant events with a non-empty `spoken_derivative` project exactly one
      locator row keyed to the owning event; all other events project none.
- [ ] Full lifecycle parity: rebuild, `project_event`,
      `update_session_projection`, `delete_session_projection`, and per-event
      delete keep the two tables coherent.
- [ ] The canonical FTS contents and any canonical search behavior are provably
      unchanged by the derivative table's presence.
- [ ] A derivative-only phrase is not matchable through the canonical FTS.
- [ ] `python -m pytest`, `python -m ruff check`, `python -m ruff format --check`
      green.

## Notes for the executor

- The single hardest property here is physical separation. Do not "reuse" the
  canonical FTS with a discriminator column and plan to filter later - the story
  treats a shared index needing post-filtering as a leak risk and a stop
  condition. Two tables.
- Keep the derivative table's row shape minimal: enough to hand task 4 the
  owning `JournalEventRef` and a snippet source. It does not need `role`,
  `source`, `event_date`, or media columns - the owner event carries those.
