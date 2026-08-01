# Task v1.8.0-28: Documentation and release verification

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-27.

## Summary

Reconcile architecture, configuration, user documentation, checks, and manual
handoff for the completed unlimited-history release.

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
