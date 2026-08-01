# Task v1.8.0-29: v1.8.0 core release verification and docs

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Release:** v1.8.0 (release-boundary card; see the story's release phasing
section). Out of numeric sequence by design: committed cards 8-28 are not
renumbered, and this card closes the v1.8.0 slice (cards 8-17).
**Depends on:** tasks v1.8.0-8 through v1.8.0-17.

## Summary

Verify and document the unlimited text-history core before the v1.8.0 release.
Scope is text-only hybrid retrieval over existing user and assistant text;
voice, annotations, and consolidation are not part of this release and are not
verified here.

## Current boundary

In scope: core-scoped scale tests, projection recovery tests, the pure
end-to-end fake backend test for text retrieval, per-turn retrieval budget and
fallback assertions, core documentation, and the v1.8.0 manual handoff.

Out of scope: transcripts, annotations, consolidation, backend reselection,
new UI behavior, and any card 18-28 responsibility.

## Requirements

- Build a large synthetic text journal with old relevant and irrelevant facts.
- Verify normal prompt size remains bounded as journal size grows.
- Verify hybrid retrieval can bring an old paraphrased fact into the final
  model pass with provenance.
- Verify exact/lexical fallback can retrieve literal identifiers when the
  semantic path is unavailable.
- Verify automatic retrieval degrades to lexical-only within the per-turn
  budget and still dispatches generation, and that the recorded fallback mode
  distinguishes timeout from unavailable.
- Exercise projection rebuild and unavailable-semantic fallback.
- Verify deletion prevents rebuild resurrection of deleted session data across
  corpus, lexical, and semantic projections.
- Preserve fork, blank-context, interruption, time-context, and current media
  behavior.
- Update `PROJECT.md` and user/config docs for the shipped core: hybrid
  retrieval architecture, morphology baseline decision, exact fallback,
  projection lifecycle, deletion behavior, the per-turn retrieval budget, and
  the explicit limitation that voice turns are not yet retrievable.
- Prepare the exact v1.8.0 manual handoff for live embedding/Ollama/resource
  checks.

## Acceptance criteria

- [ ] Pure end-to-end fake backend test covers old-fact text retrieval.
- [ ] Prompt budget remains bounded under large text history.
- [ ] Per-turn retrieval budget, degradation, and fallback-mode reporting are
      tested.
- [ ] Recovery and deletion paths are tested for corpus, lexical, and semantic
      projections.
- [ ] No raw journal or curated memory file is modified by retrieval.
- [ ] Core architecture, user, and config docs match the shipped code and name
      the voice limitation.
- [ ] Pure automated suite and Ruff checks are green.

## Stop conditions

- Stop if scale behavior grows linearly in prompt size or turn latency.
- Stop if recovery can resurrect deleted derived data.
- Stop if end-to-end behavior requires raising the tool-call budget.
- Stop if core docs reveal an implementation/architecture contradiction.
- Stop if a manual live check is required but cannot be handed off clearly.

## Verification

- Core scale/recovery/e2e tests.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run manual handoff for live model/resource checks.
