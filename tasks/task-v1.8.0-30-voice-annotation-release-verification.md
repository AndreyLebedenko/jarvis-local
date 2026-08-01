# Task v1.8.0-30: v1.8.1 voice and annotation release verification and docs

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Release:** v1.8.1 (release-boundary card; see the story's release phasing
section). Out of numeric sequence by design: committed cards 8-28 are not
renumbered, and this card closes the v1.8.1 slice (cards 18-23, 26).
**Depends on:** tasks v1.8.0-18 through v1.8.0-23 and v1.8.0-26.

## Summary

Verify and document voice and annotation retrieval before the v1.8.1 release,
after transcripts and annotations join the searchable corpus. Consolidation
and the media lifecycle are not part of this release and are verified by the
final card 27.

## Current boundary

In scope: scale and e2e tests over the expanded text surface, transcript and
annotation retrieval verification, confirmation of the card 26 regression
result, v1.8.1 documentation, and the v1.8.1 manual handoff.

Out of scope: consolidation, media reduction, backend reselection, and any
card 24-25 or final card 27-28 responsibility.

## Requirements

- Verify voice turns become retrievable after explicit local transcription,
  with provenance back to their source events.
- Verify annotation text is retrievable and remains size-capped, visible,
  editable, and traceable to raw source events.
- Confirm the card 26 retrieval-quality regression met its predeclared
  thresholds over the expanded corpus, and that raw-text baseline cases from
  the original benchmark did not regress.
- Verify appending a transcript or annotation updates the derived projections
  incrementally without rebuilding the whole session.
- Verify deletion removes transcript and annotation derived records and a
  rebuild cannot restore them.
- Update `PROJECT.md` and user/config docs for transcription and annotation
  behavior, controls, and limits.
- Prepare the exact v1.8.1 manual handoff for live transcription and
  resource checks.

## Acceptance criteria

- [ ] Voice turns are retrievable after transcription in a pure fake-backend
      test.
- [ ] Annotation retrieval and audit constraints are tested.
- [ ] The card 26 regression result is recorded and does not weaken thresholds
      after seeing results.
- [ ] Incremental update and deletion for transcripts and annotations are
      tested.
- [ ] v1.8.1 docs match the shipped code.
- [ ] Pure automated suite and Ruff checks are green.

## Stop conditions

- Stop if transcript or annotation integration regresses the raw-text
  benchmark cases.
- Stop if the expanded corpus contradicts the recorded retrieval decision.
- Stop if v1.8.1 docs reveal an implementation/architecture contradiction.
- Stop if a manual live check is required but cannot be handed off clearly.

## Verification

- v1.8.1-scoped scale/e2e tests.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run manual handoff for live transcription/resource checks.
