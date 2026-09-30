# Bug report: external annotations can lower the recall of eligible annotations

Commit: `924a5af` (main after v2.0 task 1). Detected by the independent review
of v2.0 task 2 (`task-v2.0-2-external-canvas-provenance.md`), on branch
`feat/v2.0-2-external-canvas-provenance` before its commit. Both effects
were reproduced in a scratch copy with real retrieval services.

## Symptoms

Recall only; no leak. After task 2, no external text (an `mcp_canvas` event,
or an `EXTERNAL_ANNOTATION` of an `--mcp-mode` session) can reach the
automatic-retrieval prompt. But external annotations still take part in the
scoring of the annotation legs, so an eligible Jarvis annotation can be
dropped even though it would be selected without them:

1. **Lexical rank inflation (reproduced).** `lexical_rank = hit.order_index +
   1` in `src/jarvis/journal/retrieval.py` counts every hit above a candidate
   in its own leg, external ones included. With 2 external annotations
   ranked above an eligible annotation, that annotation arrives with
   `combined_rank` 1 but `lexical_rank` 3. Its relevance is 1/3 < 0.5
   (`minimum_relevance`), so `select_automatic_retrieval_passages()` skips it
   as weak. With no external annotations it is selected.
2. **Semantic gate participation (by code reading).** `_apply_relative_gate`
   computes its cutoff over the fetched pool. An external annotation can set
   the pool's `top` score, and eligible annotations below the resulting cutoff
   are removed before any eligibility check.

## Suspected cause

Task 2 enforces eligibility after per-leg scoring: in `_collect_candidates`
(via `required_eligibility`) and again in `select_automatic_retrieval_passages()`.
The leg scores themselves are computed over pools that still contain
ineligible candidates.

## Temporary decision

Deferred. It is recall-only and limited to the annotation legs: the event legs
keep external events out through the `("text",)` source pre-filter. External
annotations exist only after the owner explicitly annotates an `--mcp-mode`
session. The contract that matters, that no external text is auto-retrieved,
holds and is tested.

Not fixed inside task 2 because that area had already gone through two fix
rounds, and the second one made things worse: an eligibility-only over-fetch
(x4 lexical rows) was added, then shown to push strong semantic-only
candidates out of the candidate limit, and removed. A third change to the
same place needs its own design rather than another patch (CLAUDE.md 0.7).

Nearby alternatives considered:
- Widening the semantic pool: rejected, because it changes the relative gate's
  median and so which candidates pass, eligible ones included.
- Inflating fetch factors: rejected, see above and
  `tasks/bug_reports/done/2026-08-08-annotation-fetch-factor-underfill.md`.

## Future considerations

- Cheap partial fix for effect 1: when `required_eligibility` is set, renumber
  `lexical_rank` among eligible candidates only (count skipped ineligible
  hits per leg in `_collect_candidates`). O(1) per candidate.
- Effect 2 needs the eligibility check before the semantic gate. That means
  reading each annotation and probing its session for every semantic hit;
  measure the cost first.
- An alternative with better recall: exclude annotations of `mcp_canvas`
  sessions from the annotation indexes' automatic-retrieval queries at the
  store level (a session filter), so they never enter the pools. This needs a
  way to pass an excluded-session set into the annotation search requests.
- Boundary: whatever the fix, the invariant stays. No external text is
  auto-retrieved, and eligibility is still enforced at
  `select_automatic_retrieval_passages()`.
