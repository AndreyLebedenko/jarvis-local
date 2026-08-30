# Backlog: Reconcile the mode-3 pass_kind gate with record_tool_boundary's precedence table

**Status:** Open. Not blocking.
**Source:** `/code-review high` structured review of task-v1.9.0-3's diff
(2026-08-30), finding 10 (Codex second-opinion: Partial - confirms two
independent mechanisms now exist, but the precedence table did not already
cover this case on its own).

## Summary

`UiTransportServer._on_model_request_started()`
(`src/jarvis/ui/transport.py:975-1006`) gates
`set_data_source(DataSource.LOCAL_ONLY)` and `set_last_model_request(...)`
behind `event.pass_kind is ModelRequestPassKind.PRIMARY`, so mode 3's
derivative sub-pass cannot downgrade an already-escalated data-source badge
or blank the chip strip. `UiStatusState.record_tool_boundary()`
(`:541-559`) already solves a related problem - "don't let a lower-priority
source downgrade an escalated one" - with an explicit `precedence` dict
(`LOCAL_ONLY < UNKNOWN < LAN < INTERNET`) instead of an ad hoc boolean gate.
These are now two separate, differently-shaped mechanisms protecting the
same field (`data_source`) from being wrongly overwritten, which the next
non-primary event type needing similar protection will have to reconcile
with rather than reuse.

## Context

- `record_tool_boundary()`'s precedence table governs escalation from tool
  calls (`DataBoundary` -> `DataSource`). It does not know about
  `ModelRequestStarted`/`pass_kind` at all - the `pass_kind is PRIMARY` check
  is a plain `if`, not a `set_data_source` call routed through any
  precedence check, so it is not "the same mechanism reused," just a
  different one added next to it for a similar reason.
- `set_last_model_request()` is unrelated to `data_source`/precedence - it
  is the chip strip's "what was this turn's own request" summary, and has
  no existing generalized guard of its own; the `pass_kind is PRIMARY` gate
  is the only thing protecting it from being blanked by a derivative pass.

## Current Boundary

- Not blocking task-v1.9.0-3, -4, or -5; explicitly deferred by owner
  decision (2026-08-30).
- Whatever shape the fix takes, `set_last_model_request()` must keep being
  primary-only (a derivative pass has no modality items of its own to
  summarize) - do not fold that call into `record_tool_boundary()`'s
  precedence table, which only concerns `data_source`.

## Possible Approaches

- Generalize `record_tool_boundary()`'s precedence table into a shared
  primitive both call sites use (e.g. a
  `_apply_if_not_downgrading(candidate: DataSource)` helper on
  `UiStatusState`), and have `_on_model_request_started()`'s
  `set_data_source(DataSource.LOCAL_ONLY)` call route through it instead of
  the current `if event.pass_kind is PRIMARY` gate - `LOCAL_ONLY` is already
  the precedence table's own floor value, so a non-primary pass proposing it
  would naturally never downgrade anything, without needing to special-case
  `pass_kind` here at all.
- Alternatively, name the current shape as the intended design (two
  independent gates for two independently-scoped concerns - "was this
  turn's data source escalated" vs. "was this turn's own request just
  this") and only tighten the comment to explain why they are deliberately
  separate rather than merging them.

## Acceptance Criteria

- [ ] Either: `_on_model_request_started()`'s `data_source` handling reuses
      `record_tool_boundary()`'s precedence mechanism instead of a separate
      ad hoc gate, with a test proving a derivative pass cannot downgrade an
      escalated data source; or: the code is left as-is with a comment
      explicitly justifying the two-mechanism design as intentional.
- [ ] `set_last_model_request()` stays gated to primary passes only,
      regardless of which approach is taken.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.

## Stop Conditions

- If generalizing the precedence table changes `record_tool_boundary()`'s
  own existing behavior for tool-call events in any observable way, stop -
  that boundary is unrelated to this backlog item and any change there
  needs its own review.
