# Task v1.8.0-10: Semantic passage and index store

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-8 and v1.8.0-9.

## Summary

Implement the selected local semantic projection as rebuildable,
source-grounded passages and index data.

## Current boundary

In scope: passage schema, embedding/index storage, rebuild, append update,
delete projection, unavailable state, health metadata, and repository tests.

Out of scope: hybrid ranking policy, model-facing tools, automatic retrieval,
working context, transcripts, annotations, and UI controls.

## Requirements

- Store semantic passages as derived data with stable source references.
- Keep passage text source-grounded; do not store generated summaries as the
  only retrievable text.
- Persist embedding/index metadata needed to reject stale model/configuration
  mismatches explicitly.
- Rebuild from the history corpus and selected effective text surface.
- Support incremental append and session deletion through task 9 lifecycle.
- Provide a typed semantic candidate query API with scores and references.
- Make unavailable or unbuilt semantic state explicit and non-mutating.
- Keep exact/prefix FTS independent and usable when semantic retrieval is
  disabled or unavailable.

## Acceptance criteria

- [ ] Rebuild creates deterministic passage references for a fixed corpus.
- [ ] Append updates only the new event's relevant passages.
- [ ] Deletion removes the session's semantic data.
- [ ] Model/config mismatch is detected clearly.
- [ ] Candidate queries return references, scores, and no authoritative facts.
- [ ] Reads do not scan raw JSONL during normal operation.

## Stop conditions

- Stop if passage identity cannot survive rebuild deterministically enough for
  audit and tests.
- Stop if the selected backend cannot represent deletion without orphaned
  vectors.
- Stop if embedding work competes unpredictably with live dialog resources.

## Verification

- Focused semantic projection tests with deterministic fakes or fixtures.
- Existing journal corpus/search tests.
- `python -m pytest`
- Ruff checks.
