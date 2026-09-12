# Task v1.9.2-8: Final spike report and owner decision (G3)

**Status:** Deferred 2026-09-12 in the full form below, under the accepted
reduction proposal (`spike-1.9.2-reduction-proposal.md`). The decision-report
function stays live in reduced form: stage 0 (card v1.9.2-9) produces its own
small decision record per the stop rule; this card's full report content
applies only if stage 1 is authorized.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Spike card (contract source):** `task-v1.9.2-1-local-answer-revision-spike.md`, G3 and Acceptance checklist.
**Depends on:** task-v1.9.2-6 (G2), task-v1.9.2-7 (Journal check).
**Created:** 2026-09-12.
**Current boundary:** Assemble the sanitized report and record the owner's
bounded decision. No production implementation, no roadmap edits beyond
status bookkeeping, no release activity in this card.

## Summary

Produce `tasks/v1.9.2-spike-report.md` as the durable decision record: all
arms, exclusions, artifact hashes/locations, and limitations; obtain the
owner's explicit G3 choice among the three predeclared outcomes.

## Report contents (from the spike card)

- All arms and exclusions with score denominators; case/repeat outcomes;
  corrected and introduced errors by severity; unnecessary edits.
- Conditional repair rate per strategy (repaired defects divided by defective
  A drafts) alongside whole-answer end-to-end quality; the story requires
  these two quantities to be distinguished.
- The defective-A-draft counts for development (G1) and held-out (G2); if the
  held-out count is below the win threshold, the outcome is reported as
  inconclusive/underpowered - a ceiling effect of the corpus, not evidence
  against the mechanism - inside outcome 3 below, never filed as
  nonqualification.
- Checker calibration and audit results, drift/version limits.
- Actual cost, latency, token usage, and consumed human time.
- Cloud privacy-policy reference/date and egress manifest summary.
- Raw artifact locations and hashes under
  `manual_check_answer_revision_out/<run-id>/` (local-only, never committed).
- Interpretation limits: repeats are not independent problems; suspicious-
  correct oversampling is not an ordinary-user error rate; Journal replay is
  not a fresh baseline.
- Win criteria phrased per the frozen protocol rule: observed stable-win rate
  with its denominator, plus an explicit statement that the stable-win count
  threshold is a floor, not an effect size; the win threshold is never quoted
  as evidence of usefulness on its own.
- Baseline B outcome stated against the pre-registered expectation: if B
  matched A's quality, the report records this as a second independent
  confirmation of the v1.8.0-22 faithfulness-trap finding on a new task class,
  not as a hurdle quietly cleared.
- Framing selection provenance stated literally: measured on development
  cases, or "selected by tiebreak, not tested" if the tiebreak resolved it.
- Explicit statement that held-out results were not used for tuning.

## G3 decision record (owner)

One of exactly three outcomes per strategy:
1. **Qualifies** for a stated bounded text-slice implementation proposal
   (which then needs its own story/task cards; text success does not license
   `text_voice` - the reasoning-off derivative check over revised answers
   remains a separate release gate).
2. **Does not meet the gate** in the tested scope; ordinary single-pass
   behavior is retained.
3. **Inconclusive/deferred** with one specific next question. The
   inconclusive label covers an underpowered corpus (win threshold
   unreachable because natural drafts were mostly correct) as well as
   missing evidence; the specific next question then names the corpus
   amendment or the follow-up measurement.

Record: no broker, settings UI, or production three-pass work starts as part
of this spike regardless of outcome.

## Also close out

- Spike card's acceptance checklist reviewed item by item against actual
  artifacts; any unchecked box explained or resolved.
- Harness disposal note: cases, rubrics, prompts, criteria, score sheets, and
  sanitized reference results survive as versioned fixtures; the harness is
  replaceable.
- Update the story card's status and `PROJECT.md` only if an architectural
  decision changes (per AGENTS.md; the spike itself normally does not).
- Durable-asset summary for future regression reuse and fresh-experiment
  rules (new experiments need new held-out cases; old cases become
  regressions).

## Boundary

- No production wiring, no config change, no release verification in this
  card. Follow-up work gets its own approved cards.

## Verification

- Report numbers cross-checked against ledger artifacts and the G2/Journal
  cards; hashes recomputed, not copied.
- `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`
  green (report-generation logic is pure-tested from task v1.9.2-3).
- Owner decision recorded verbatim with date in the protocol approval section
  and the report.

## Acceptance criteria

- [ ] `tasks/v1.9.2-spike-report.md` complete per the contents list.
- [ ] Spike acceptance checklist fully discharged or explicitly annotated.
- [ ] G3 outcome recorded as one of the three bounded choices with the
      owner's date and any dissent noted.
- [ ] Durable assets (cases, rubrics, frozen prompts, reference results)
      listed with locations for later reuse.
- [ ] Stop for human review before closing the spike task card and the story.