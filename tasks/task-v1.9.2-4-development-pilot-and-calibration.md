# Task v1.9.2-4: Development pilot and checker calibration

**Status:** Planned. Blocked on G0 approval recorded in the protocol.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Spike card (contract source):** `task-v1.9.2-1-local-answer-revision-spike.md`, Phase 2 and G1.
**Depends on:** task-v1.9.2-3 (tested harness, prepared handoff).
**Created:** 2026-09-12.
**Current boundary:** Human-run live batch execution and scoring on
development cases only. No held-out output is generated or opened before G1
freezes the protocol.

## Summary

Execute the 6-case development pilot and the injected-defect diagnostics
through the prepared harness, calibrate the GLM checker against the 20
human-scored sheets, select the revision framing and reasoning variant, and
bring the results to the owner for the G1 feasibility and freeze decision.

## Human-run steps (agent prepares the handoff, does not execute)

1. **Preflight probes (2 local calls):** record model version/digest/template,
   context capacity, effective request options, reasoning level of baseline A.
2. **GLM calibration (20 cloud calls):** score the 20 preauthored sheets
   BEFORE any development output exists. Calibration needs no local calls and
   no development output. Record item-level true/false positives/negatives and
   unclear outputs, separately on decisive items. Human adjudication overrides
   GLM. An early calibration failure disqualifies the checker before the local
   budget is spent; a failed calibration stops for a revised proposal or an
   explicit human-scoring fallback approved by the owner - GLM's uncalibrated
   scores are never relied on (spike card phase 2 rule).
3. **Development batch (42 local calls):** per case - A generation (reused),
   B high baseline, revision A, revision B, then framing choice before the
   high-revision call, high-reasoning revision (better framing), C, I.
   Framing choice rule: fewer introduced material errors, then more corrected
   defects; ties keep first-person A. High revision only if it corrects at
   least one additional material error, adds none, and meets the two-pass
   latency bound.
4. **Injected diagnostics (18 local calls):** 6 fixed candidates through the
   selected R and C/I. Not counted as live generation or as natural defects;
   kept out of held-out gate numbers.
5. Record actual per-stage timings and scoring minutes/sheet; derive whether
   the full matrix fits the agreed owner-time and machine-time budgets.

## G1 inputs the owner confirms

Real timings, scoring effort, cap completion (no systematic censoring),
checker calibration against the acceptance rules (zero missed material/critical
defects; at most 1 false-defect sheet of 10 correct; at least 90% determinate
item agreement; at most 2 unclear sheets of 20), exact local/cloud model
metadata, selected framing/reasoning, remaining budget. At most 2/42
development calls incomplete, each explained. Failures mean a revised protocol
or a reduced/stopped proposal - never trimming failed outputs or automatic
fallback.

Freeze before held-out output: prompts, options, rubric versions, framing,
thresholds, matrix.

## Boundary

- 60 local calls + 20 cloud calls maximum in this phase (2 preflight + 42 + 18
  local; 1 synthetic connectivity probe + 20 calibration cloud are inside the
  spike card's 233-call cloud ceiling).
- No prompt tuning beyond the predeclared framing comparison; the selection is
  recorded as exploratory, not confirmation evidence.
- No held-out case text is read into any prompt.
- Infrastructure errors stop the run per AGENTS.md.

## Verification

- Agent-side: handoff document self-sufficiency review (commands, credential
  name, setup steps, stop/resume semantics all named literally with sources).
- Human-reported: ledger completeness for all dispatched IDs; score sheets for
  42 + 18 development calls and 20 calibration sheets; timing and effort
  numbers recorded in the pilot section of the report skeleton.
- G1 decision recorded in the protocol's approval section with protocol
  version/hash before any card v1.9.2-5 work starts.

## Acceptance criteria

- [ ] All 60 permitted local calls dispatched through the harness ledger with
      immutable terminal statuses; no silent retries.
- [ ] Framing and reasoning selection recorded with the predeclared rule.
- [ ] GLM calibration measured against all four acceptance rules; failures
      escalated, not papered over.
- [ ] G1 freeze recorded (or a revised-protocol proposal returned) before any
      held-out execution.
- [ ] Human time and machine time within or explicitly below the proposed
      caps, with deviations explained for approval.