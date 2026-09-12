# Task v1.9.2-5: Held-out paired experiment

**Status:** Planned. Blocked on G1 freeze.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Spike card (contract source):** `task-v1.9.2-1-local-answer-revision-spike.md`, Phase 3.
**Depends on:** task-v1.9.2-4 (G1 freeze recorded).
**Created:** 2026-09-12.
**Current boundary:** Human-run live execution of the frozen held-out matrix.
No prompt change, no threshold change, no new case after seeing held-out
performance.

## Summary

Run the frozen paired experiment over 18 held-out cases x 2 seeds with the
selected revision framing and reasoning variant, score all four answer sheets
per case/repeat, and assemble complete per-case evidence for the audit card.

## Frozen matrix (from the spike card)

- 18 cases x 2 seeds (19201, 19202) x 5 local calls: A generation, B high
  baseline, selected R, C, I = 180 local calls.
- A is generated once per case/repeat and reused across arms; report full user
  costs R = A+R and I = A+C+I including prefill and reasoning.
- Four final-answer sheets per case/repeat (A, B, R, I) = 144 sheets, GLM-
  scored independently without arm labels; pure checks run first; all four
  answers of a case scored close together.
- Sequential dispatch; at most one checklist request per sheet; cloud calls
  stay inside the spike card's remaining ceiling.

## Scoring rules (predeclared; no post-hoc edits)

- Pairwise direction from predefined material items: win = fixes at least one
  material defect without adding one; loss = introduces a material defect;
  otherwise tie (minor edits reported separately).
- Stable win per case: both repeats win, or one wins and the other ties. Any
  repeat loss counts as a case loss. Mixed win/loss is never netted.
- Report each category separately, especially suspicious-correct and
  uncertainty cases. Do not present the deliberate oversampling of hard
  categories as an ordinary-user error rate.
- Missing/invalid checker verdicts are unscored, not passes; cloud errors or
  unclear outputs cannot become passing scores.
- Report actual B/R/I latency in the preagreed bands; state when B is not a
  close cost match; do not equate a reasoning label with matched compute.

## Boundary

- Complete matrix or inconclusive; no case replacement after seeing
  performance; no retries beyond the ledger's explicit-resume rule.
- No Journal data in this phase.
- Infrastructure errors stop per AGENTS.md.

## Verification

- Human-reported: complete ledger for 180 local calls and 144 scored sheets;
  per-case/repeat outcome table with win/loss/tie and stability flags;
  category breakdowns; latency table for all arms.
- Agent-side: handoff self-sufficiency review; consistency check of score
  denominators (18 cases x 2 repeats x 4 arms = 144) and direction rules in
  the aggregation code (pure logic, already tested in task v1.9.2-3).
- Output feeds task v1.9.2-6: every alleged material/critical introduced
  error, every unclear or conflicting decisive assessment, and every claimed
  stable-win case must be auditable from the ledger artifacts.

## Acceptance criteria

- [ ] 180/180 local calls and 144/144 sheets processed with immutable ledger
      statuses and no silent retry.
- [ ] Scores computed under frozen rubric versions and the predeclared
      direction/stability rules only.
- [ ] Category-level results reported separately with denominators.
- [ ] Latency and cost recorded per arm, including shared-generation savings
      reported separately from full user costs.
- [ ] No protocol, prompt, or case change occurred during the phase.
- [ ] Stop for the audit card before any G2 computation is trusted.