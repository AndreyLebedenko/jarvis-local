# Task v1.9.2-6: Human audit, drift check, and G2 gate

**Status:** Deferred 2026-09-12. Retained as the draft of stage 1 (repair
measurement) under the accepted reduction proposal
(`spike-1.9.2-reduction-proposal.md`); the G2 numeric table is superseded for
the immediate experiment by stage 0's stop rule (card v1.9.2-9) and would be
re-derived for stage 1 on its own G0 gate if stage 1 is authorized.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Spike card (contract source):** `task-v1.9.2-1-local-answer-revision-spike.md`, Phase 4 and G2.
**Depends on:** task-v1.9.2-5 (complete held-out run).
**Created:** 2026-09-12.
**Current boundary:** Human scoring work over existing artifacts plus the
predeclared G2 computation. No new model calls except the end-of-run
calibration repetition; no threshold edits.

## Summary

Audit every score that could support or undermine a qualification claim,
repeat the calibration subset to detect checker drift, and compute G2 from
complete audited evidence - or mark the outcome inconclusive per the
predeclared rules.

## Audit obligations (deduplicated before estimating effort)

The human reviews:
- every alleged material/critical introduced error;
- every unclear or conflicting decisive assessment;
- every case contributing to a claimed stable win;
- a random 10 of the passing held-out sheets (seed 19204), including
  suspicious-correct cases - the missed-defect check.

If audit demand exceeds the owner-time budget: stop for a smaller scope or an
inconclusive result. Audits are never skipped to make the numbers.

## Checker drift check

Repeat the 20 calibration sheets through GLM at the end. Same acceptance rules
as phase 2. Any new missed decisive defect or changed decisive calibration
verdict requires adjudication before the gate is trusted. Freeze/report cloud
metadata and alias limitations; no silent rescoring until agreement improves.

## G2 computation (evaluate complete pairs only)

Thresholds live in the spike card (`task-v1.9.2-1`, G2 section) and the
machine-readable protocol sidecar - not restated here, so a G0-approved
adjustment changes exactly those two places. This card's computation applies
the frozen table to audited data:

- Complete 18 cases x 2 repeats required for an affirmative outcome; missing
  cases give inconclusive, with failure rates reported.
- The introduced material/critical defect test uses the denominator fixed at
  G0 (all 18 cases, or 15 excluding correct-but-suspicious with a narrowed
  "qualifies except for correct-but-suspicious inputs" outcome). Whichever
  denominator the protocol freezes, the stress-category outcomes are still
  computed and reported separately.
- Reachability: count held-out A drafts (case x repeat) that violated at
  least one material rubric item. If fewer than 3 such drafts exist, the win
  threshold was unreachable; the outcome is recorded as inconclusive/
  underpowered with the corpus ceiling stated - never as nonqualification.
- Report the conditional repair rate per strategy: repaired defects divided
  by defective A drafts, alongside whole-answer end-to-end quality.
- Critical vetoes are never averaged away. Severity per the frozen rubric.
- Meeting the counts qualifies a strategy only for a bounded text-slice
  proposal, never default-on use.

## Boundary

- No new cases, no re-runs of failed arms, no rescoring outside the drift
  check.
- Agent prepares the aggregation/audit worksheet and computes G2 arithmetic
  (pure logic); the human performs all semantic judgments.

## Verification

- Audit records for each obligation category with dispositions (confirmed/
  refuted/adjusted) and effect on the outcome.
- End calibration results vs phase-2 calibration, with any drift adjudication.
- G2 table filled from audited data, or an explicit inconclusive record with
  the missing-evidence list.

## Acceptance criteria

- [ ] All audit obligations discharged or the outcome downgraded accordingly.
- [ ] Drift check run and adjudicated before gate trust.
- [ ] G2 computed only from complete audited case pairs; denominators stated.
- [ ] Result recorded as qualifies / does not meet the gate in this scope /
      inconclusive - no post-hoc threshold changes.
- [ ] Stop for human review before the Journal card runs.