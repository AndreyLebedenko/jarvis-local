# Task v1.8.0-17: Automatic retrieval wiring

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-15 and v1.8.0-16.

## Summary

Retrieve bounded historical passages before request assembly and feed them
into the working context.

## Current boundary

In scope: orchestration integration, retrieval latency metrics, unavailable
semantic fallback, recent-context fallback, and fake-service tests.

Out of scope: changing hybrid ranking, adding tools, transcripts,
annotations, and UI.

## Requirements

- Invoke automatic retrieval once per ordinary user turn before assembly.
- Use exact fallback behavior when the semantic projection is unavailable.
- Do not perform an additional generative model call.
- Bound retrieval latency and result size.
- Treat retrieval failure as degraded context, not failed user turn, unless
  source consistency is at risk.
- Record retrieval count, accepted passages, elapsed time, and fallback mode.
- Ensure retrieved passages are not persisted as new facts.

## Acceptance criteria

- [ ] Old relevant paraphrased facts can enter the assembled prompt.
- [ ] Unrelated old events do not enter the prompt.
- [ ] Semantic unavailable mode still allows exact identifier retrieval.
- [ ] Retrieval failure is observable and does not mutate history.
- [ ] Prompt budget remains respected.

## Stop conditions

- Stop if retrieval regularly pollutes context with weak matches.
- Stop if retrieval latency cannot be bounded.
- Stop if failure handling would silently hide projection corruption.

## Verification

- Focused orchestration tests with fake retrieval service.
- End-to-end fake backend test slice.
- `python -m pytest`
- Ruff checks.
