# Annotation fetch factor can underfill results when stale rows crowd the top

**Detected at commit:** 30ab8ad (task v1.8.0-23 slice 2)
**Status:** Accepted boundary, deferred by owner decision (2026-08-08).

## Symptoms

`HistoryRetrievalService.retrieve` (and through it `search_history` and
automatic pre-turn retrieval) can return fewer than the requested `limit`
annotation-backed results even though valid annotations exist. It happens only
when, for the query, the number of stale annotation projection rows
(deleted/dismissed since projection, still present through a race or projection
lag) ranked above the first valid annotation exceeds the source fetch window.

The event corpus is unaffected in practice; the concern is specific to the
annotation lexical/semantic sources because dismiss/delete is an expected
transient there.

## Suspected cause

Each annotation source is asked for only `request.limit * _LEXICAL_FETCH_FACTOR`
candidates before hydration:

- `src/jarvis/journal/retrieval.py:450` (annotation lexical),
- `src/jarvis/journal/retrieval.py:476-477` (annotation semantic).

Slice 2 fixed the "already fetched but stale" case: fusion no longer truncates
before hydration, and the fully ranked fused list is walked in `read_events`-sized
chunks, filling `limit` from candidates that survive hydration
(`_collect_candidates`). But that only rescues rows the sources actually
returned. A valid annotation ranked just below the `limit * 3` fetch window is
never fetched, so hydration never sees it and it cannot fill a slot vacated by a
stale row above it.

## Temporary decision

Keep the fixed `limit * _LEXICAL_FETCH_FACTOR` fetch, do not paginate.

Chosen over the nearby alternatives:

- **Paginate annotation sources until `limit` survive hydration** (Codex's
  suggestion): correct, but needs a paging cursor on both annotation query APIs
  and a fetch loop in the service, i.e. new surface and its own tests - out of
  scope for this slice, and speculative until the failure is observed.
- **Raise `_LEXICAL_FETCH_FACTOR` for annotations:** only widens the window, does
  not remove the boundary, and enlarges the per-turn hydration cost for every
  query to defend a transient that the projections already work to prevent.

Rationale: only `ACTIVE` annotations are indexed; dismiss/delete triggers
`AnnotationOverlayChanged` reprojection that removes the row, so a stale
annotation exists in the index only inside a narrow race/lag window. For that to
underfill results, more than `2 * limit` such stale rows must rank above the
first valid annotation for the same query - implausible at the small limits the
live paths use (automatic retrieval `candidate_limit` 8, `search_history` max 6).
The event path carries the identical fetch-factor tradeoff and has been accepted
since task 11.

## Future considerations and boundaries

- If real usage ever shows annotation underfill (telemetry: accepted passage
  count persistently below requested with a non-empty annotation index), revisit
  with pagination: add a stable cursor to `AnnotationSearchIndex.search` /
  `AnnotationSemanticIndex.query` and have `_collect_candidates` request further
  pages until `limit` valid candidates survive hydration or the source is
  exhausted, keeping each `read_events` batch within its reference ceiling.
- Any such change belongs with the retrieval-quality regression work (card 26),
  not this card, and must not reintroduce pre-hydration truncation.
- Do not "fix" this by inflating the fetch factor; that trades constant cost for
  no guarantee.
