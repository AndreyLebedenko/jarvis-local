# Proposal: reduce the v1.9.2 spike to a staged experiment

**Status:** Accepted by the owner on 2026-09-12. The staged shape, stage 0's
sample size (~30), the severity-based operational definitions, the stop rule
with the exploratory-prompt reading of inertness, the two owner-time slots
(30 min pre-marking + 40 min scoring), and hand-marking of the response mode
are approved. Cards `-2` through `-8` move to a deferred state per the
transition map in the story card; a new stage-0 card is the active slice.
Not a card, not a gate record.
**Created:** 2026-09-12.
**Relates to:** `story-v1.9.2-local-generation-critique-integration.md`,
`task-v1.9.2-1-local-answer-revision-spike.md` and cards `-2` through `-8`,
`spike-1.9.2-tasks-notes.md`, `spike-1.9.2-tasks-notes-2.md`.
**Origin:** Two review passes checked the cards for internal consistency and
found them consistent. This proposal steps back from that and asks whether the
apparatus serves the spike's own question. It argues that it does not yet, and
that a much smaller first experiment answers the decisive part of it.

## The contrast

The spike asks one question: does independent local revision improve the final
answer enough to justify its cost.

The budget answers a different one. Of 260 planned local calls, 240 go to an
authored corpus, 18 to real turns, and 2 are preflight probes. The authored
corpus cannot settle the question in either direction:

- If the naturally generated drafts turn out to be mostly correct, the win
  threshold is unreachable and the run is underpowered. No information.
- If the corpus is built so that defects reliably appear, the observed win rate
  is a property of the corpus and does not transfer to ordinary use. The cards
  already forbid quoting it as a base rate.

Either way the expensive arm produces a number that cannot be cited. The only
arm carrying an ordinary-use base rate is phase 5: up to six Journal turns and
twelve human comparisons, about five percent of the budget - and it is the one
arm that is currently under-specified and, against the actual journal schema,
unexecutable (see "The one real blocker" below).

## The asymmetry the current design ignores

Measuring repair requires a defect. Defects have to be found or manufactured,
and that is what makes the authored corpus, its rubrics, its splits, the cloud
checker, its calibration and its drift checks expensive.

Measuring damage requires nothing. Any answer already believed correct is
material, and the Journal is full of them at zero authoring cost.

Damage is also the decisive quantity for the rollout decision. If revision
degrades correct answers at a material rate, no repair rate buys that back and
the whole ladder is dead. If it does not, then building the repair-measurement
apparatus becomes worth its price.

The current plan spends its budget in the opposite order.

## Proposed shape

### Stage 0: damage and inertness probe (proposed first and only authorized step)

Take approximately 30 completed text turns from the Journal whose published
answers the owner marks correct **before** any revision runs. Run one revision
pass over each. Count how often the revision made a correct answer worse, and
how often it changed nothing at all.

- One arm. No critic, no integrator, no held-out split, no development split.
- No cloud. The material is Journal content, which never leaves the machine, so
  no GLM checker, no calibration sheets, no drift check, no egress manifest, no
  provider billing question.
- Human scoring only: unchanged / minor change / improved / damaged, with a
  short reason. Correctness is pre-declared, so damage is judged against a
  standard fixed before the output existed.
- Roughly 30 local calls.

Operational definitions, frozen before the first revision runs, together with
the prompt, the eligibility rule and the stop rule:

- **Damaged** means the revision introduced a defect of severity material or
  critical, on the existing severity axis: material = wrong result, lost
  constraint, or consequential caveat dropped; critical = an error unacceptable
  for its hypothetical consequence.
- **Minor change** means a presentation nuisance that does not change a required
  result. Minor changes are counted and reported separately and do not enter the
  stop rule in either direction.
- **Substantive change** means any change that is not minor by that definition:
  the revision altered a required result, a constraint, a claim, or a caveat -
  whether for better or worse.

Owner time, as two explicit slots rather than one round hour:

| Slot | Work | Proposed cap |
| --- | --- | --- |
| Pre-marking | Mark ~30 published answers correct/not before any revision exists; mark each turn's response mode by hand | 30 minutes |
| Scoring | Compare each draft with its revision and label it | 40 minutes |

Proposed stop rule, for owner approval before the run:

| Outcome | Reading | Next step |
| --- | --- | --- |
| Damaged >= 3 of 30 | Revision degrades correct answers at a material rate | Stop. Ladder rejected on the real request distribution |
| Damaged 1-2 of 30 | Signal present, sample too small to size it | One bounded follow-up on damage only |
| Damaged 0 and unchanged >= 25 of 30 | Inert **at these settings and with this prompt** | Cheap exploratory prompt refinement, then decide - not an immediate stop |
| Damaged 0 and changes substantive | Safe enough to be worth measuring repair | Stage 1 |

The inertness row is not new: it is the story-notes appendix A "step 0", kept as
a feasibility check. Its reading, however, is narrower than that appendix
proposed and the story already says why: an unchanged answer can mean the answer
was correct, the instruction was ineffective, an error went unseen, or there was
too little variation. Inertness at the default prompt is therefore not inertness
of the mechanism. It buys a cheap exploratory pass at the revision instruction -
which is exactly the kind of tuning the later stages forbid, and which is
affordable here precisely because no held-out claim depends on it - and only
then a decision.

Stage 0 does not escape the hardest piece of engineering entirely: revising a
past turn still needs its evidence packet, and a reviser starved of context will
damage answers out of ignorance rather than out of a defect in the mechanism.
Mitigation: restrict eligibility to turns whose packet is trivially
reconstructible - no tool execution, no media, no dependence on retrieved
history or memory. That shrinks the eligible pool and must be reported as a
scope limit, but it keeps the measurement fair without building a full
historical-context reconstructor.

### Stage 1: repair measurement, conditional on stage 0

Only if stage 0 shows no damage and non-trivial change. This is where the
authored corpus, per-case rubrics, the development/held-out split and the
numeric win threshold earn their cost, because by then there is a reason to
believe the mechanism is safe and active. The existing cards `-2` through `-6`
are the draft of this stage and are retained, not discarded.

Whether the cloud checker is worth its own validation is re-decided here, not
now. At the scale stage 1 would actually need after stage 0 has filtered the
question, human scoring of 30-60 sheets is likely cheaper than calibrating a
checker, repeating the calibration for drift, and auditing its passes - work the
current envelope prices at 30 of the owner's 120 minutes before a single
experimental sheet is scored.

### Stage 2: three passes, conditional on stage 1

The three-pass arm currently carries about 40 percent of the call budget while
having to clear the longest conditional chain in the plan: it must beat the
two-pass arm, which must beat two single-pass baselines, against a recorded
prior in `PROJECT.md:194-198` where more reasoning bought nothing on
faithfulness traps. Deferring it until two passes show something removes that
share of the budget at almost no loss of information. Deferral is not
refutation, and the report must say so.

## What this removes now

Not deleted - deferred, with their drafts retained:

- The 24 authored cases with rubrics, the development/held-out split, the
  injected-defect diagnostics.
- The GLM checker end to end: 20 calibration sheets, 233 cloud calls, the drift
  repeat, the egress manifest, the billing verification, the network-boundary
  clause in the handoff.
- The three-pass arm and its comparisons.
- G0's numeric table, G1's freeze, G2's qualification criteria.

What remains for stage 0 is one sampling rule, one prompt, one stop rule, a
local-only harness, and an hour of the owner's attention.

## The one real blocker

Stage 0 lives entirely in the Journal, so the finding that survives this
reduction is the schema gap. `JournalRecorder.record_assistant`
(`src/jarvis/journal/recorder.py:88-117`) writes only `outcome`,
`spoken_derivative` and `spoken_derivative_interrupted` into the assistant
event's metadata. `ResponseMode` (`src/jarvis/dialog/response_mode.py:38`) never
reaches the Journal at all. Consequences for any Journal-based sampling:

- `text_voice` turns are detectable, by the presence of the derivative.
- `text` and `voice` turns are indistinguishable from each other. A `voice`
  answer revised under a text output contract would be "improved" into a canvas,
  which measures contract conversion, not revision quality.
- The reasoning level in force for a past turn is not recorded anywhere.

**Chosen for stage 0: the owner marks the mode by hand** during pre-marking, and
the reasoning-level requirement is dropped from the selection record. At 30
turns this costs minutes and it is the only option that does not trade a known
distinction for convenience.

Sampling "turns without a spoken derivative" was considered and rejected: it
excludes `text_voice` while silently mixing `text` and `voice`, which is the
same defect finding 20 caught in card 7. Persisting mode and reasoning level in
the event metadata is the correct long-term fix, but it is a runtime change and
outside the spike, so it is filed instead as
`tasks/bug_reports/2026-09-12-journal-turn-does-not-record-response-mode-or-reasoning-level.md` -
any future Journal-based experiment hits the same hole.

## What the owner decides

1. Accept the staged shape, or keep the current single large experiment.
2. If staged: approve stage 0's sample size, the severity-based definitions of
   damaged and substantive, the stop rule, and the two owner-time slots.
3. Confirm that cards `-2` through `-8` move to a deferred state rather than
   being closed, so their content is reusable as the stage 1 draft.

**Decided 2026-09-12:** all three accepted as proposed; the mode is hand-marked
by the owner (bug report filed for the durable fix); card 7 is superseded by
stage 0 rather than deferred; card 8 stays live in a reduced form for the
stage-0 decision record. A bounded damage follow-up, if the 1-2/30 row
triggers, gets its own stage-0-format card with a fresh run-id and the same
frozen eligibility/scoring rules. Phase 5 (card 7) is recorded as absorbed by
stage 0 with its task changed from regression check to damage probe.

Accepting this proposal changes no settled project contract. It changes the
order in which the spike spends the owner's attention: the cheapest decisive
question first, and the expensive apparatus only after that question has been
answered in the direction that makes it worth building.
