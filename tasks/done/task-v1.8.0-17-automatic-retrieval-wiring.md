# Task v1.8.0-17: Automatic retrieval wiring

**Status:** Completed.
**Story:** `tasks/done/story-v1.8.0-unlimited-conversation-history.md`
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
- Use exact/lexical fallback behavior when the semantic projection is
  unavailable.
- Also degrade to lexical-only retrieval when a turn's semantic retrieval
  (including query embedding) exceeds the per-turn budget from task 8, rather
  than delaying generation. Bounded-time degradation and unavailable-projection
  degradation are both first-class, not error paths.
- Do not perform an additional generative model call.
- Bound retrieval latency and result size against the recorded per-turn budget.
- Treat retrieval failure as degraded context, not failed user turn, unless
  source consistency is at risk.
- Record retrieval count, accepted passages, elapsed time, and fallback mode
  (full hybrid, lexical-by-timeout, or lexical-by-unavailable).
- Ensure retrieved passages are not persisted as new facts.

## Acceptance criteria

- [ ] Old relevant paraphrased facts can enter the assembled prompt.
- [ ] Unrelated old events do not enter the prompt.
- [ ] Semantic unavailable mode still allows exact identifier retrieval.
- [ ] A turn that exceeds the per-turn budget degrades to lexical-only and
      still dispatches generation without waiting on the semantic path.
- [ ] The recorded fallback mode distinguishes timeout from unavailable.
- [ ] Retrieval failure is observable and does not mutate history.
- [ ] Prompt budget remains respected.

## Stop conditions

- Stop if retrieval regularly pollutes context with weak matches.
- Stop if per-turn retrieval latency cannot be bounded or cannot degrade to
  lexical-only within its budget.
- Stop if failure handling would silently hide projection corruption.

## Verification

- Focused orchestration tests with fake retrieval service.
- End-to-end fake backend test slice.
- `python -m pytest`
- Ruff checks.
