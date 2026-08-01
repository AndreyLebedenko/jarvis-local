# Task v1.8.0-27: Scale, recovery, and end-to-end verification

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-26.

## Summary

Verify the integrated unlimited-history design on large synthetic history,
projection recovery paths, and end-to-end fake-backend dialog behavior.

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

- [ ] Pure end-to-end fake backend test covers old-fact retrieval.
- [ ] Prompt budget remains bounded under large history.
- [ ] Recovery and deletion paths are tested.
- [ ] No raw journal or curated memory file is modified by retrieval.
- [ ] Existing automated suite is green.

## Stop conditions

- Stop if scale behavior grows linearly in prompt size or turn latency.
- Stop if recovery can resurrect deleted derived data.
- Stop if end-to-end behavior requires raising the tool-call budget.

## Verification

- Scale/recovery/e2e tests.
- `python -m pytest`
- Ruff checks.
- Manual handoff for live model/resource checks.
