# Task v1.8.0-28: Final documentation and release verification

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
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

- [ ] Architecture docs match implementation.
- [ ] User docs explain what history retrieval can and cannot do.
- [ ] Config docs are complete and default-safe.
- [ ] Manual handoff commands are exact.
- [ ] Pure automated suite and Ruff checks are green.
- [ ] Release notes call out local-only retrieval and exact fallback.

## Stop conditions

- Stop if documentation reveals an implementation/architecture contradiction.
- Stop if final verification fails outside the task scope.
- Stop if a manual live check is required but cannot be handed off clearly.

## Verification

- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run manual handoff commands.
