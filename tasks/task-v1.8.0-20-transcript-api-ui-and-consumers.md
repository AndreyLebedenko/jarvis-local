# Task v1.8.0-20: Transcript API, UI, and retrieval consumers

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-18 and v1.8.0-19.

## Summary

Expose transcript controls and include effective transcripts in corpus,
lexical, and semantic retrieval projections.

## Current boundary

In scope: authenticated local API, Journal UI controls, transcript effective
text reads, projection refresh, and retrieval tests.

Out of scope: changing transcription model behavior, annotations,
consolidation, and working-context policy.

## Requirements

- Add local authenticated endpoints for transcript read/edit/generate actions.
- Respect Hidden mode for UI visibility and API access.
- Display transcript status and editable text in the Journal surface.
- Feed effective transcripts into lexical and semantic projections through
  lifecycle-owned updates.
- Preserve raw event text and media.
- Keep transcript text source-framed when retrieved.

## Acceptance criteria

- [ ] Users can view and edit transcript overlays.
- [ ] Generated transcripts are auditable and editable.
- [ ] Search/retrieval can find transcript-only voice content.
- [ ] Hidden mode suppresses transcript UI/API visibility.
- [ ] Projection updates do not rebuild unrelated sessions.

## Stop conditions

- Stop if transcript edits cannot update retrieval projections consistently.
- Stop if UI controls imply automatic background transcription.

## Verification

- API, UI, projection, and retrieval tests.
- `python -m pytest`
- Ruff checks.
