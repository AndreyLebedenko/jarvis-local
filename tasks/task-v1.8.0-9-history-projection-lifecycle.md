# Task v1.8.0-9: History projection lifecycle and incremental indexing

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-8.

## Summary

Move startup, append, deletion, rebuild, and shutdown ownership for history
projections out of the UI and into one history-domain lifecycle owner.

## Current boundary

In scope: lifecycle coordinator, projection registration, startup readiness,
incremental raw event projection, lexical FTS updates, selected semantic
projection hooks, deletion orchestration, app wiring, and UI ownership
removal.

Out of scope: semantic passage implementation details beyond the selected
projection interface, tools, automatic retrieval, transcripts, annotations,
consolidation, and UI redesign.

## Requirements

- Introduce one history-domain lifecycle owner constructed by `build_app()`.
- Treat corpus rows, lexical search rows, and semantic retrieval data as
  registered derived projections.
- At startup validate or rebuild projections independently of whether Status
  Console is enabled.
- At startup rebuild the semantic projection when its recorded backend identity
  (embedding model, dimension, prompt config) differs from the configured
  `[history.semantic]` backend. Never serve stored vectors produced by a
  different model than the current query embedder.
- Subscribe to `JournalEventAppended` and update exactly that referenced
  event. Do not delete/re-index the whole session.
- Current-session events become readable and retrievable after append
  processing completes.
- Provide one delete-session operation that removes raw session data and all
  derived projections or reports consistency failure honestly.
- `UiTransportServer` calls history services for reads/deletion and keeps UI
  push/rendering responsibilities only.
- Hidden mode suppresses visibility, not internal projection consistency.
- Shutdown waits for in-flight projection writes through an explicit seam.

## Acceptance criteria

- [ ] Projections work when no Status Console is created.
- [ ] One appended event causes one incremental projection update.
- [ ] Current-session lexical search does not rebuild the whole session.
- [ ] Selected semantic projection has explicit enabled/unavailable states.
- [ ] A configured semantic-backend change triggers a projection rebuild, not a
      silent mixed-space read.
- [ ] Session deletion removes raw and derived data through one owner.
- [ ] No UI class owns a search-index mutation method afterward.
- [ ] Startup and shutdown ordering are deterministic and tested.

## Stop conditions

- Stop if one recoverable deletion protocol cannot cover raw files and
  derived stores.
- Stop if bus ordering can expose a referenced event before raw append
  completion.
- Stop if startup requires blocking the event loop on an unbounded rebuild
  without a readiness state.
- Stop if ownership extraction creates a circular dependency.

## Verification

- Focused journal, lifecycle, app-wiring, and transport tests.
- A pure test proving append work remains linear across a long session.
- `python -m pytest`
- Ruff checks.
