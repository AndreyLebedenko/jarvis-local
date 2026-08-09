# Task v1.8.0-29: v1.8.0 core release verification and docs

**Status:** Completed 2026-08-09. Implemented and verified by
`tests/test_history_core_scale_recovery_e2e.py` (10 tests, real
`HistoryCorpusRepository`/`SemanticPassageIndex`/`HistoryRetrievalService`
instances wired into a real `Orchestrator`, no live Ollama). The scale sweep
hit the card's own "stop if scale behavior grows linearly in ... turn
latency" condition for real: `SemanticPassageIndex.query()` does an unbounded
brute-force cosine scan with measurable near-linear growth (500 events 7ms ->
20,000 events 209ms). Owner decision, 2026-08-09: accept as a known,
documented limit at personal-journal scale rather than fix it here (out of
this card's no-backend-change boundary); recorded in `PROJECT.md` and
`tasks/bug_reports/2026-08-02-semantic-hot-path-scan-remains-unbounded.md`.
Docs were initially under-scoped (README left untouched, and then the voice
limitation was phrased in a way that read as advertising unreleased
voice/annotation/consolidation capability) - both caught and fixed via
Codex stop-time review; see `README.md`/`README.ru.md`'s "Unlimited
conversation history" sections. The owner's live manual handoff (2026-08-09)
confirmed item 1 (semantic quality) matches the task-8 record almost exactly
with no drift; items 2-3 surfaced a real, separately tracked defect instead
of a clean measurement - see
`tasks/bug_reports/2026-08-09-semantic-rebuild-500-on-long-passage-context-window.md`
- and are left open by owner decision rather than blocking this card.
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

- [x] Pure end-to-end fake backend test covers old-fact text retrieval.
- [x] Prompt budget remains bounded under large text history.
- [x] Per-turn retrieval budget, degradation, and fallback-mode reporting are
      tested.
- [x] Recovery and deletion paths are tested for corpus, lexical, and semantic
      projections.
- [x] No raw journal or curated memory file is modified by retrieval.
- [x] Core architecture, user, and config docs match the shipped code and name
      the voice limitation.
- [x] Pure automated suite and Ruff checks are green.

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
