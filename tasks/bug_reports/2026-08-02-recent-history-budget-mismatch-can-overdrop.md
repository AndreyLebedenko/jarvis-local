# Recent history is selected twice with different budgets, which can over-drop passages

**Detected at commit:** `f63e961` (`codex/v1.8.0-task17-automatic-retrieval-wiring`).
**Status:** Open, low-impact follow-up.

## Symptoms

Automatic retrieval currently builds its query context from a recent-history
selection capped by `recent_history_max_tokens`, then the working-context
assembler independently re-selects recent history under the smaller final
available prompt budget.

That means the retrieval selector can deduplicate a candidate against a recent
turn that was present when the query was built, but is no longer present in
the final assembled prompt. In that case the selector may drop a passage that
would have been safe and relevant in the actual prompt.

The effect is deterministic and low-impact, but it does reduce recall in a way
that is hard to see from the current telemetry.

## Suspected cause

The orchestration path uses two different recent-history cuts:

- `_resolve_automatic_retrieval()` builds the query from a recent-history
  selection capped by the configured recent-history window.
- `assemble_working_context()` later re-samples recent history against the
  final prompt budget after retrieved passages are accounted for.

Because the second selection is tighter, the overlap gate in the retrieval
selector can observe context that never reaches the final model prompt.

## Temporary decision

Leave this as a documented follow-up rather than widening task v1.8.0-17.
Fixing it cleanly likely means changing the orchestration shape so recent
history is sampled once, then reused consistently for both retrieval query
construction and final prompt assembly.

## Future considerations and boundaries

- If this becomes visible in quality or recall metrics, the fix should align
  query construction and final prompt assembly around the same sampled recent
  suffix.
- The natural place to revisit it is alongside the later large-scale
  verification work, not by pulling the next release card into task 17.
