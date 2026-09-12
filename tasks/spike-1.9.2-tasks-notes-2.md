# Review notes 2: v1.9.2 spike task cards

**Status:** Second agent review of the spike card set, after the first review's
findings were partly absorbed. Input for owner review, not a decision record.
**Created:** 2026-09-12.
**Reviewed documents:** `story-v1.9.2-local-generation-critique-integration.md`,
`task-v1.9.2-1-local-answer-revision-spike.md` (committed in `cd03eed`),
`task-v1.9.2-2` through `-8`, and both review-notes files, at their working-tree
state on 2026-09-12.
**Companion files:** `story-v1.9.2-local-generation-critique-integration-notes.md`
holds findings 1-17 against the story drafts; `spike-1.9.2-tasks-notes.md` holds
findings 18-24 against the first task-card set. Numbering continues here from 25.
**Boundary:** Review only. No card, protocol, fixture, or harness was changed.

## Overall assessment

The set remains executable and the decomposition remains right. Scientific
hygiene is above average for a spike of this size: rubrics predate outputs,
development and held-out splits are disjoint, post-hoc threshold edits are
forbidden, and the three outcome labels are honest.

Arithmetic still checks out everywhere it can be checked against the spike
card's ceilings: 2 + 42 + 18 + 180 + 18 = 260 local calls,
1 + 20 + 36 + 12 + 144 + 20 = 233 cloud calls, 144 = 18 x 2 x 4 held-out sheets,
36 = 6 x 6 development sheets, 12 = 6 x 2 injected sheets, 18 = 6 x 3 Journal
calls. The exception is card 4's own phase budget - see finding 25.

Findings 25-29 block G0. 30-31 are gate criteria that do not do the work they
appear to do. 32-35 are consistency and lifecycle maintenance.

## Status of findings 18-24

The first review's defects were absorbed, but not uniformly:

- **18 (calibration ordered after the step depending on it):** fixed in card 4,
  which moves calibration to human-run step 2 and cites the spike card's rule.
  Not fixed in card 1, which remains the contract source - see finding 26. The
  budget consequence was also missed - see finding 25.
- **19 (G2 denominator):** raised to an explicit G0 decision in card 2 and
  carried into card 6, but card 6 states the alternative denominator wrongly -
  see finding 28.
- **20 (response-mode filter for the Journal sample):** fixed in card 7, with
  the recoverability of the mode stated and the reasoning level now recorded.
- **21 (win threshold is a floor):** absorbed into card 2's protocol content
  rules and card 8's report contents. The related but distinct question of
  whether the threshold is reachable at all is not addressed - see finding 29.
- **22 (baseline B likely degenerate):** absorbed as a pre-registered
  expectation in card 2 and a required report statement in card 8. Good.
- **23 (framing chosen by tiebreak):** raised as an explicit G0 budget decision
  in card 2 and a required report statement in card 8. Its call arithmetic is
  off - see finding 33.
- **24 (duplicated G2 table, scattered seeds):** fixed. Card 6 references the
  spike card and sidecar instead of restating thresholds; card 3 names the
  sidecar as the single authoritative seed enumeration.

`spike-1.9.2-tasks-notes.md` itself was not updated and still reads as a list of
open defects - see finding 32.

## Finding 25: card 4's phase budget is wrong on both axes, and 36 sheets have no owner

`task-v1.9.2-4-development-pilot-and-calibration.md:60` declares
"60 local calls + 20 cloud calls maximum in this phase" and then enumerates
"2 preflight + 42 + 18 local", which is 62, not 60. The acceptance criterion
"All 60 permitted local calls dispatched" repeats the same number.

The cloud side is worse than an off-by-one. The line counts 1 connectivity probe
plus 20 calibration sheets, which is already 21, and omits the 36 development
final sheets entirely. Those sheets are in the spike card's cloud ceiling, and
they must be scored inside this phase: the framing selection rule - fewer
introduced material errors, then more corrected defects - is item-level scoring
of the development outputs, and finding 18's fix was precisely to calibrate GLM
first so that it can perform that scoring.

Actual phase 2 consumption is 62 local and 57 cloud calls. Neither card 1's
phase 2 nor card 4 says who scores the 36 development sheets; the intent is only
recoverable from the cloud ceiling's line item. An executor following card 4's
boundary literally stops at 20 cloud calls, with the framing choice unmade.

Fix: correct both totals in card 4, name GLM as the development-sheet scorer in
card 1 phase 2, and state the 36 sheets in card 4's boundary.

## Finding 26: the calibration-order fix landed in the slice, not in the contract source

Card 1 is committed and is declared the contract source in every slice's header.
Its phase 2 still runs the 42-call development batch and the injected
diagnostics first, and only then says "Calibrate GLM against the 20 human-scored
sheets before relying on its scores" (`task-v1.9.2-1:197-217`). Card 4 executes
the corrected order.

Two documents now disagree about the order of a step whose whole point is that
it must come first, and the authoritative one carries the defect. This is the
duplication hazard finding 24 described, realized in the opposite direction:
not a restated threshold drifting, but a correction applied to only one copy.

Fix: amend card 1's phase 2. The slice should not be the place where the
contract is corrected.

## Finding 27: the CLI contract has no seam for the framing selection

The spike card's CLI contract exposes `run --phase pilot` as one command over
all 42 development calls. But the framing choice must happen inside that batch,
after revision A and revision B and before the high-reasoning revision, and it
depends on cloud scoring that lives in a separate `score-cloud` command and on a
human judgment. There is no pause, no `--framing` flag, no command that records
the selection, and no defined way for the later held-out `run` to learn which R
was selected.

Card 3 implements the contract literally, so the gap propagates into the
harness. An executor following card 4 reaches step 3 and has to stop and ask -
the failure mode the testing protocol's self-sufficiency rule exists to prevent.

Fix: either split the pilot into two phases (`pilot-framing`, then the rest), or
add an explicit selection-recording command that writes the choice into the
protocol sidecar that the held-out run reads. Whichever is chosen, card 1's CLI
contract, card 3's deliverables, and card 4's step list must agree.

## Finding 28: card 6 states the alternative G2 denominator as 18, not 15

`task-v1.9.2-6-audit-drift-and-g2-gate.md:48` offers the G0 choice as
"all 18 cases, or 18 excluding correct-but-suspicious". The held-out set is 18
cases with 3 in the correct-but-suspicious category, so the second option is 15.
Card 2:78 states it correctly.

This is the single number that decides the outcome of the gate, in the card that
computes the gate. Fix it in card 6.

## Finding 29: a ceiling effect is not distinguishable from a negative result

The story names the risk directly: "a ceiling-effect dataset cannot measure
correction benefits". No card converts it into a check.

G2 requires at least 3 stable case wins out of 18. A win requires the revision
to fix at least one material defect. If fewer than 3 of the 18 natural A drafts
contain a material defect by their own rubric, the threshold is unreachable
regardless of how good revision is. The recorded outcome would then be "does not
meet the gate in this tested scope" - a statement about the corpus presented as
a statement about the mechanism. Card 8's three outcome labels have no place to
put "the experiment could not have detected the effect".

Nothing in G1 measures the natural material-defect rate of A on the 6
development cases, and nothing in G2 requires reporting it on held-out.

The data already exists: A is one of the four scored sheets per case and repeat,
scored against the same rubric as the others. The fix is interpretive, not
experimental:

- G1 reports the count of development cases whose A draft violated at least one
  material rubric item, and flags an underpowered corpus before 180 calls are
  spent.
- G2 reports the same count over held-out repeats.
- If that count is below the win threshold, an unmet threshold is recorded as
  inconclusive/underpowered, not as nonqualification.

This is the highest-value change in this review. Without it, the most likely
outcome of the run - "the natural drafts were mostly correct" - is filed as
evidence against revision.

## Finding 30: the G2 latency band is anchored to B and therefore does not bind

Two of the table's latency rows divide by baseline B's median. `PROJECT.md:197`
records that on this model `high` cost about 5x `off` (~5.5 s versus ~1.05 s
warm) for zero measured quality difference on faithfulness traps, and card 2
already pre-registers that B is expected to be degenerate in quality.

If B is roughly 5x A, then "at most 2.5 x B median" permits roughly 12.5 x A,
while the two-pass strategy costs roughly 2 x A. The row passes automatically.
It still passes if the selected R is the high-reasoning variant: A + 5A over
5A = 1.2. The three-pass row behaves the same way. Only the absolute p90 caps
(60 s and 90 s) constrain anything; the incremental row, I over R at roughly
3A / 2A = 1.5 against a 1.8 limit, is marginal but real.

The user pays relative to A, not to B. Anchor the ratio to A and keep the ratio
to B as a separate reported comparison, or state explicitly that the B ratio is
a documentation column and the absolute p90 is the operative cost gate.

## Finding 31: "the two-pass latency bound" is undefined where G1 uses it

Card 1:203 and card 4 make the high-reasoning revision conditional on satisfying
"the two-pass latency bound". Latency bounds exist only in the G2 table, and are
expressed as ratios against the median of held-out baseline B, which by
construction does not exist at G1 time. The condition is unevaluable at the
moment it must be evaluated.

Fix: give the pilot its own absolute bound, or derive the pilot bound from the
development B timings that phase 2 does produce.

## Finding 32: the first notes file is now stale in a way that misleads

`spike-1.9.2-tasks-notes.md` presents findings 18, 20 and 24 as open defects,
including the walkthrough "as ordered, one of two things must happen, and
neither is written down". All three are fixed in the cards. A reader reaching
that file after the cards will either re-fix a fixed problem or distrust the
review.

The story-notes file already solves this well: findings 1-7 carry an explicit
line saying draft 2 closed them and that they are retained as the record of why
the draft changed. Apply the same treatment - or point the first notes file at
this one's "Status of findings 18-24" section.

## Finding 33: card 2's framing-budget option does not price itself correctly

Card 2's second G0 question offers "2-3 development cases specifically for the
framing comparison (+14 local calls)". 14 is 2 cases at 7 calls; 3 cases is 21.
Separately, the 260-call ceiling in card 1 explicitly forbids adding exploratory
variants, so choosing this option is not only a case-count decision but a
ceiling amendment. Both belong in the question.

## Finding 34: card 1 is the parent of cards 2-8, but is numbered as their peer

Card 1 defines the contract that all other cards reference. It cannot be
completed and moved to `tasks/done/` on its own under the task-documentation
workflow; it closes only when card 8 closes. Numbering it `task-v1.9.2-1`
asserts a peer relationship that does not exist, and the workflow rule for task
cards will misfire on it.

The repository already has the right shape for this:
`tasks/spike-kling-integration.md` is a spike document, not a numbered task.
Either rename card 1 to `spike-v1.9.2-local-answer-revision.md` and renumber the
slices, or state in card 1 that its lifecycle is bound to card 8's completion.

## Finding 35: the story and roadmap do not know that cards 2-8 exist

The story's header still reads "Active task:
`task-v1.9.2-1-local-answer-revision-spike.md`", and its "Ordered work and
decision gates" step 1 is not mapped onto the slices that implement it.
`roadmap-v1.9-v2.0.md:141` likewise names only the first card. Once the slice
set is accepted, both should name it, so that the entry point for a reader
arriving from the roadmap is the executable sequence rather than the contract.

## Smaller notes

- **Conditional repair rate is required by the story and not carried into the
  cards.** The story asks to "distinguish conditional repair rates from
  whole-answer end-to-end quality". Cards 5, 6 and 8 report corrected and
  introduced errors by severity, which is the numerator, but no card asks for
  the rate conditional on A actually being defective. This is the same quantity
  finding 29 needs, so both are fixed by the same reporting line.
- **The proposed ignore rule does not match the file's convention.** Cards 1 and
  2 mandate `/manual_check_answer_revision_out/`; all eight existing raw-output
  entries in `.gitignore:13-20` are written without the leading slash.
  Functionally equivalent here, but the convention in that file is the other
  one.

## Recommendation

Findings 25-28 and 31 are text corrections inside one editing pass. Finding 29
is one reporting line in G1, one in G2, and one outcome label in card 8.
Finding 27 is the only one that touches the harness design, and it is cheaper to
settle before card 3 implements the CLI than after. Finding 19's denominator and
finding 33's ceiling remain owner decisions at G0.

None of this reopens the design. The spike's question, corpus shape, gate
structure and egress boundary all survive the review unchanged.
