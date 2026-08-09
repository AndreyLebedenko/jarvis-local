# Task v1.8.0-28: Final documentation and release verification

**Status:** Completed 2026-08-09. Docs-only card, no code changed. Added a
consolidated "Architecture v1.8.0-v1.8.2 (unlimited conversation history)"
section to `PROJECT.md`; flipped `README.md`/`README.ru.md`'s consolidation
framing from "later work" to shipped, added the local-only-retrieval/
exact-fallback release-notes callout, and closed the now-stale "no retention
policy" Known Issues bullet; closed
`tasks/bug_reports/2026-07-17-journal-retention-policy.md` (its own named
closure condition - the consolidation pipeline shipping - is met); confirmed
config examples need no changes; consolidated every manual handoff command
from the whole story into one list. Full record in `PROJECT.md`'s "v1.8.2
final documentation and release verification" entry. This closes the whole
`story-v1.8.0-unlimited-conversation-history.md` story.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
**Release:** v1.8.2 (final release-boundary card; see the story's release
phasing section).
**Depends on:** task v1.8.0-27.

## Summary

Reconcile architecture, configuration, user documentation, checks, and manual
handoff for the fully completed unlimited-history story after consolidation.
The v1.8.0 and v1.8.1 releases carry their own scoped docs in cards 29 and 30;
this card is the final reconciliation across the whole story.

## Current boundary

In scope: `PROJECT.md`, README/user docs, config examples, manual handoff,
release notes, and final verification commands.

Out of scope: feature implementation, backend reselection, new UI behavior,
and post-release roadmap expansion.

## Requirements

- Update `PROJECT.md` with final hybrid retrieval architecture and verified
  facts.
- Document exact fallback, semantic retrieval locality, projection lifecycle,
  deletion behavior, and user-visible limitations.
- Update config examples for any new history/retrieval settings.
- Document manual verification for live embeddings/Ollama/resource behavior.
- Reconcile task-card statuses and move completed cards according to workflow
  only after owner review.
- Run final project checks.

## Acceptance criteria

- [x] Architecture docs match implementation.
- [x] User docs explain what history retrieval can and cannot do.
- [x] Config docs are complete and default-safe.
- [x] Manual handoff commands are exact.
- [x] Pure automated suite and Ruff checks are green.
- [x] Release notes call out local-only retrieval and exact fallback.

## Stop conditions

- Stop if documentation reveals an implementation/architecture contradiction.
- Stop if final verification fails outside the task scope.
- Stop if a manual live check is required but cannot be handed off clearly.

## Verification

- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run manual handoff commands.
