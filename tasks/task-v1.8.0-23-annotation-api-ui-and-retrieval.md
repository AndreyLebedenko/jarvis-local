# Task v1.8.0-23: Annotation API, UI, and retrieval projections

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-21 and v1.8.0-22.

## Summary

Expose annotation controls and include annotation text in retrieval without
treating it as authoritative source history.

## Current boundary

In scope: authenticated local API, Journal UI controls, projection updates,
retrieval framing, and tests.

Out of scope: changing generator prompts, consolidation execution, and
working-context assembly.

## Requirements

- Add local authenticated endpoints for annotation read/edit/generate actions.
- Respect Hidden mode for UI visibility and API access.
- Show annotation source references in the Journal surface.
- Feed annotations into lexical and semantic projections as derived text with
  explicit source framing.
- Retrieved annotations must not replace raw event/range reads.
- Projection updates are lifecycle-owned.

## Acceptance criteria

- [ ] Users can view and edit annotation overlays.
- [ ] Retrieval can find annotation text and expose it as derived data.
- [ ] Source references are visible and preserved.
- [ ] Hidden mode suppresses annotation UI/API visibility.
- [ ] Projection updates do not rebuild unrelated sessions.

## Stop conditions

- Stop if annotation retrieval cannot distinguish derived text from raw text.
- Stop if UI makes generated annotations look authoritative.

## Verification

- API, UI, projection, and retrieval tests.
- `python -m pytest`
- Ruff checks.
