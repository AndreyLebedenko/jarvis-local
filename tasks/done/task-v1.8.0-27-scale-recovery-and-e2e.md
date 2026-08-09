# Task v1.8.0-27: Final integrated scale, recovery, and end-to-end verification

**Status:** Completed 2026-08-09. Implemented and verified by
`tests/test_consolidation_release_e2e.py` (4 tests): the real
`ConsolidationPlanner`/`ConsolidationExecutor`/`ArchiveOverlayRepository`
stack, wired exactly as `jarvis/app.py` wires it, added to the real
corpus/semantic/transcript/annotation/retrieval stack already built for
cards 29-30. Consolidation's own crash-recovery, partial-failure, and
per-session-lock behavior are already thoroughly covered by task v1.8.0-25's
own suite and were not repeated here - this card verified only the
integration delta: retrieval, prompt-size boundedness, and
deletion-cannot-resurrect all continue to hold once far-consolidation has
actually run and removed a session's audio. Correction confirmed while
implementing: there is no age-based near/far window anywhere in the shipped
system (no `[consolidation]` config section exists); "near" vs "far" is
purely the story's conceptual naming for "not yet explicitly
far-consolidated" vs "explicitly far-consolidated", never an age policy.
Full record in `PROJECT.md`'s "v1.8.2 final integrated release verification"
entry.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
**Release:** v1.8.2 (final release-boundary card; see the story's release
phasing section).
**Depends on:** tasks v1.8.0-24, v1.8.0-25, and v1.8.0-30.

## Summary

Verify the fully integrated unlimited-history design, including consolidation
and the media lifecycle, on large synthetic history, projection recovery
paths, and end-to-end fake-backend dialog behavior. This is the final
verification over the whole story; the v1.8.0 and v1.8.1 boundaries are
verified by cards 29 and 30.

## Current boundary

In scope: scale tests, recovery tests, pure end-to-end fake backend test,
latency/size assertions, and manual handoff updates.

Out of scope: new feature behavior, backend selection, UI redesign, and live
hardware/model execution beyond handoff.

## Requirements

- Build a large synthetic journal with old relevant and irrelevant facts.
- Verify normal prompt size remains bounded as journal size grows.
- Verify hybrid retrieval can bring an old paraphrased fact into the final
  model pass with provenance.
- Verify exact fallback can retrieve literal identifiers.
- Exercise projection rebuild and unavailable semantic fallback.
- Verify deletion prevents rebuild resurrection of deleted session data.
- Preserve fork, blank-context, interruption, time-context, and current media
  behavior.

## Acceptance criteria

- [x] Pure end-to-end fake backend test covers old-fact retrieval.
      (Text/voice/annotation cases already covered by cards 29-30; this
      card added the consolidation-integrated case.)
- [x] Prompt budget remains bounded under large history.
- [x] Recovery and deletion paths are tested.
      (Extended to the archive run store; consolidation executor's own
      crash recovery already covered by task 25.)
- [x] No raw journal or curated memory file is modified by retrieval.
- [x] Existing automated suite is green.

## Stop conditions

- Stop if scale behavior grows linearly in prompt size or turn latency.
- Stop if recovery can resurrect deleted derived data.
- Stop if end-to-end behavior requires raising the tool-call budget.

## Verification

- Scale/recovery/e2e tests.
- `python -m pytest`
- Ruff checks.
- Manual handoff for live model/resource checks.
