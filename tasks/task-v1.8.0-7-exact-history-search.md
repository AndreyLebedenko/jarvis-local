# Task v1.8.0-7: Exact and prefix history search

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-5 and v1.8.0-6.

## Summary

Add rebuildable FTS5 search over raw user and assistant text, with typed
filters and stable references. Preserve the current Journal UI search through
an adapter while moving search ownership into the history corpus.

## Context you need

- `src/jarvis/journal/search.py` and `tests/test_journal_search.py`.
- Task 5 corpus schema and task 6 read API.
- `src/jarvis/ui/status_console.py`: current search-hit payload.
- `src/jarvis/ui/transport.py`: current `/api/journal/search` handler.
- PROJECT.md's verified Russian exact/prefix limitation.

## Current boundary

- In scope: FTS schema, rebuild integration, typed search request/result,
  ranking/order modes, filters, snippets, and compatibility for existing UI
  search.
- Out of scope: transcripts, annotations, embeddings, automatic retrieval,
  model tools, and live incremental index ownership.

## Requirements

- Index non-empty raw user and assistant text. System provenance stays
  readable through task 6 but is not searched by default.
- Search returns `JournalEventRef`, timestamp, role, source, a plain-text
  snippet, and score/order metadata.
- Support query, inclusive date/time bounds, session ids, roles, sources, and
  a strict result limit.
- Preserve exact/prefix Unicode behavior for Russian.
- Define two explicit order modes:
  - relevance for model/history-domain retrieval;
  - chronological for the existing Journal UI.
- Snippet markers remain data, never HTML. Existing safe UI highlighting
  remains unchanged.
- Date-only UI search remains supported.
- Rebuild creates event and FTS projections transactionally.
- Keep a compatibility surface only where needed by current transport/UI;
  new domain consumers use the new typed API.

## Acceptance criteria

- [ ] User and assistant text are searchable by exact and prefix queries.
- [ ] Role/source/session/date filters compose correctly.
- [ ] Relevance and chronological modes are deterministic.
- [ ] Every hit reads back to the same event through task 6.
- [ ] Existing Journal search behavior and injection-safe highlighting stay
      green.
- [ ] Search before a corpus exists is a clear unavailable/empty state, not a
      write side effect.

## Stop conditions

- Stop if relevance ranking and current UI chronology cannot share one
  explicit API without hidden mode switches.
- Stop if FTS row identity can drift from `JournalEventRef`.
- Stop if preserving UI snippets would require embedding markup in corpus
  text.
- Stop if schema changes require raw-journal migration.

## Verification

- `python -m pytest tests/test_journal_search.py`
- Relevant UI transport and journal-view search tests.
- Ruff checks.
