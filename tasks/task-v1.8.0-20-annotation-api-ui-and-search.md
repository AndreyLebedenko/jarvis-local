# Task v1.8.0-20: Annotation API, UI, and search

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-19-annotation-generator.md`
- `task-v1.8.0-7-exact-history-search.md`

## Summary

Expose annotation viewing, editing, deletion, and explicit generation through
the authenticated Jarvis API and Journal UI, and include annotations in exact
history search.

## Context you need

- `src/jarvis/ui/transport.py`
- `src/jarvis/ui/status_console_ui/`
- Journal UI static files and tests
- task 7 exact-search result model
- task 18 annotation repository
- task 19 generator

## Current boundary

- In scope: annotation API/UI integration and exact-search integration.
- Out of scope: automatic consolidation and semantic embeddings.

## Requirements

- Add authenticated API operations for annotation list, edit, delete, and
  explicit generation.
- Apply Hidden-mode content suppression consistently.
- Show generated-versus-edited state and source links in the Journal UI.
- Render text safely and follow existing localization conventions.
- Index annotation text with session and source provenance.
- Distinguish annotation hits from raw-event and transcript hits in typed
  search results.
- Remove stale search content on edit/delete.
- Prevent generation from overwriting concurrent user edits.

## Acceptance criteria

- [ ] All new API operations have authentication, validation, and Hidden-mode
  tests.
- [ ] Search can return an annotation and lead back to its source range.
- [ ] UI tests cover empty, generating, generated, edited, failed, and Hidden
  states.
- [ ] Editing or deleting an annotation updates exact search immediately.
- [ ] Raw journal and transcript overlays remain unchanged.

## Stop conditions

- Stop if the task 7 search result contract cannot represent non-event hits
  without an architectural choice.
- Stop if source navigation requires an unspecified Journal UI behavior.

## Verification

- Focused API, Journal UI, exact-search, and concurrency tests.
- Static JavaScript checks defined by the project.
- `python -m pytest`
- Ruff checks.
