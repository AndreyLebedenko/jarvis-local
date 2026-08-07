# Task v1.8.0-23: Annotation API, UI, and retrieval projections

**Status:** Approved. Retrieval contract owner-approved 2026-08-07.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-21 and v1.8.0-22.

## Summary

Expose annotation controls and include annotation text in retrieval without
treating it as authoritative source history.

The retrieval contract the task 21 store deliberately deferred is decided here:
one hybrid retrieval surface returning typed candidates over separate
annotation lexical/semantic projections. Full contract in `story-v1.8.0`
decision 5 and `PROJECT.md`; the ordered slices below implement it.

## Current boundary

In scope: authenticated local API, Journal UI controls, separate annotation
lexical/semantic projections, lifecycle-owned reprojection, single-surface
retrieval framing, and tests.

Out of scope: changing generator prompts, consolidation execution, and
working-context assembly. Selector anti-pollution ranking (card 16) and the
retrieval-quality regression (card 26) are not this card.

## Retrieval contract (agreed)

- One retrieval surface. `HistoryRetrievalService` queries event and annotation
  lexical and semantic sources and fuses them into one ranked result; the single
  per-turn query embedding is reused across both semantic indices. No separate
  annotation retrieval API.
- Separate derived projections. Annotation text is indexed in its own lexical
  (FTS, pymorphy-normalized) and semantic (passages keyed by `annotation_id`)
  stores, physically distinct from the event projections. Annotation rows never
  enter the event tables.
- Typed candidates. A candidate is either an event (`JournalEventRef` ->
  `read_events`) or an annotation (`annotation_id` + `AnnotationTarget` ->
  `AnnotationOverlayRepository`), the latter carrying `kind=annotation`,
  `source`, and target, surfaced as delimited derived data, never as a raw turn.
- Eligible for automatic and explicit retrieval; not filtered at the surface.
- Lifecycle-owned reprojection via a new `AnnotationOverlayChanged` signal that
  add/edit/delete/generate publish; session deletion clears the annotation
  lexical/semantic projections too.

## Ordered implementation slices (separate branches)

1. Annotation lexical + semantic projections and `AnnotationOverlayChanged`
   reprojection through `HistoryProjectionLifecycle` (+ session-delete fan-out).
2. Single-surface typed-candidate retrieval: discriminated candidate identity,
   annotation source querying, fusion, annotation hydration, derived framing
   propagated to the working-context passage shape.
3. Authenticated annotation API endpoints (read/list/edit/generate) with Hidden
   mode, mirroring the transcript endpoints.
4. Journal UI annotation controls (session/range annotations, source
   references, edit, generate) with Hidden-mode suppression.

## Requirements

- Add local authenticated endpoints for annotation read/list/edit/generate
  actions, keyed by session and `annotation_id` (generate by whole-session or
  event range).
- Respect Hidden mode for UI visibility and API access.
- Show annotation source references in the Journal surface.
- Feed annotations into separate lexical and semantic projections as derived
  text with explicit source framing, consumed through the single hybrid surface.
- Retrieved annotations must not replace raw event/range reads.
- Projection updates are lifecycle-owned via `AnnotationOverlayChanged`.

## Acceptance criteria

- [ ] Users can view and edit annotation overlays.
- [ ] Retrieval can find annotation text and expose it as a typed derived
      candidate (`kind=annotation`, source, target), never as a raw turn.
- [ ] Source references are visible and preserved.
- [ ] Hidden mode suppresses annotation UI/API visibility.
- [ ] Projection updates do not rebuild unrelated sessions.
- [ ] Session deletion clears the annotation lexical and semantic projections
      and a rebuild cannot restore them.

## Stop conditions

- Stop if annotation retrieval cannot distinguish derived text from raw text.
- Stop if UI makes generated annotations look authoritative.

## Verification

- API, UI, projection, and retrieval tests.
- `python -m pytest`
- Ruff checks.
