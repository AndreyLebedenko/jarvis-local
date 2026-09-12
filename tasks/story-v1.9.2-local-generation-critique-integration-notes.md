# Review notes: story v1.9.2 local generation, critique, and integration

**Status:** Agent review across three drafts. Findings 1-7 (draft 1) and 8-12
(draft 2) are closed. Findings 13-17 (draft 3) are open; finding 17 covers the
owner's external-scorer proposal.
**Created:** 2026-09-12.
**Updated:** 2026-09-12.
**Reviewed document:** `story-v1.9.2-local-generation-critique-integration.md`
(draft 1, then draft 2, both 2026-09-12).
**Commit at review time:** `ed3873c`.
**Boundary:** Review only. No implementation, no task card, no change to the
reviewed story, the roadmap, or `PROJECT.md`.
**Naming:** deferred by owner decision. `ReThink` and `Review` are working
labels in finding 7 and appendix A, not proposed final names.

## Summary position

The draft's boundaries are sound: role isolation, the frozen source packet, the
ban on `message.thinking` crossing passes, "only integration is canonical", and
the exclusion of D/C from memory and retrieval are all correctly stated, and the
draft is honest that more passes are a hypothesis rather than a guarantee.

Two objections are structural: the quality premise has a recorded negative prior
inside this project (finding 1), and the proposed broker duplicates a scheduler
that v2.0 already owns (finding 3). One objection is about shape: a
substantially cheaper form of the same capability is not considered (finding 4).
One is a missed failure mode (finding 5). Two are process (findings 2 and 6).
Finding 7 records the owner's counter-proposal from the same dialog - a graded
ladder whose middle rung is a much smaller feature than the drafted one - and
appendix A is the minimal plan for that rung.

Recommendation: replace draft 1's single three-pass feature with the ladder of
finding 7, implement only its middle rung first (appendix A), keep the
evaluation as one throwaway card, and set the stop rule numerically before
running it.

**Draft 2 closed findings 1-7.** The sections above are retained as the record
of why draft 1 changed, not as open objections; where draft 2 chose differently
from a recommendation here, draft 2 is the current position and the reasons are
listed under "Draft 2 review" below. `Proposed reduction` near the end of this
file is superseded by draft 2's own "Ordered work and decision gates".

## Finding 1: the quality premise has a negative prior in this project

`PROJECT.md` records an owner-supervised live A/B on `gemma4:12b-it-qat`
(annotation generator, task v1.8.0-22, 2026-08-07, `PROJECT.md:178`): on
objective faithfulness traps
(self-correction 3.11-not-3.10, numeric 26->12, distractor grounding, reasoning
trace leakage) `reasoning=high` produced zero improvement over `off`, both
perfect, at roughly 5x latency (~5.5 s versus ~1.05 s warm). That measurement
covers the annotation pass and a narrower task class than open-ended answers, so
it does not settle this story. It is still a measured fact about this model:
spending additional reasoning compute did not buy quality on the class of
failure the critique role is meant to catch.

The wider prior points the same way. Same-model self-critique without an
external signal is well documented to damage already-correct answers at a rate
comparable to the errors it fixes, because the critic shares the generator's
blind spots and has an instruction-following incentive to produce findings.

Consequences for the draft:

- The evaluation must be designed so regressions are its primary output, not
  improvements. The acceptance criteria already say this ("records both
  corrected mistakes and regressions"); the task sequence does not yet make
  regression the leading measurement.
- "Include a comparable-compute single-pass baseline where practical" (last
  paragraph of Verification) is not a footnote. It is the second arm of the
  experiment and it decides the story. One pass at high reasoning, given the
  same wall-clock budget as three roles, is the thing three roles must beat.
  If it is not beaten, the story closes at card 1.
- The draft should cite the v1.8.0-22 finding explicitly as the prior it is
  trying to overturn, so the spike is not designed in ignorance of it.

## Finding 2: the only available asymmetry is not named as the mechanism

One local model means one set of weights and one set of blind spots. A different
system prompt is a weak asymmetry. The levers that actually differ are per-role
reasoning level, temperature/seed, and role framing.

Open decision 3 currently proposes "separate role prompts, measured reasoning
defaults". That is too soft to drive an experiment. Recommendation: make
per-role reasoning asymmetry an explicit variable of the evaluation, with
`generation=off / critique=high` as the named candidate. It is the only
configuration with a stated mechanism for why the critic would see what the
generator missed, and it is directly comparable against the finding-1 baseline
because the v1.8.0-22 A/B used the same two levels.

## Finding 3: the broker is premature and duplicates v2.0's scheduler

`roadmap-v1.9-v2.0.md` already assigns v2.0 a general idle-time cognition queue
with typed jobs, a preemptible worker, and once-coherent commits, and states
explicitly that it must be built general rather than as a one-off. The proposed
"local broker" with a job ID, typed stage results, and a seven-state lifecycle
is a second scheduler in everything but name. The draft acknowledges the
collision ("do not introduce competing schedulers silently") without resolving
it.

The broker is also not needed for the capability. `run_derivative_pass()`
(`src/jarvis/app.py:1426`) already demonstrates the exact pattern this story
needs: an additional dispatch with its own system prompt and its own
`ReasoningLevel`, reusing the turn's `_active_chat_task` and
`_interrupt_requested` so the existing interrupt hotkey cancels it, followed by
an honest journal write that marks a partial result as partial. Critique and
integration are structurally the same operation. Proposed task cards 2 and 3
collapse into one, and the lifecycle states, late-result rejection, and restart
persistence questions disappear with them.

If foreground waiting turns out to be unacceptable, that is an argument for
sequencing v2.0's queue before this feature, not for building a private
scheduler now.

## Finding 4: a form at roughly half the cost is not considered

The draft assumes review happens before the user sees anything: D and C are
hidden, only F is published. An alternative shape:

**Review on request over the answer already given.** Jarvis answers normally,
streaming, at today's latency. The user reads it and asks for a review. Jarvis
then runs critique and integration over its own last answer and publishes the
revision as a new turn.

What this buys:

- Two passes instead of three; the generation pass is the ordinary turn.
- The low-latency path is untouched in every case, including when review is
  never requested.
- D is already a legitimate canonical turn, so the entire "D must not flash as a
  final answer or reach TTS" problem, and the machinery built to guarantee it,
  disappear.
- No eligibility policy is needed for media or tool-dependent turns (open
  decision 2): the source turn has already happened, with whatever evidence it
  used.
- Provenance is trivial: a revision is an ordinary assistant turn referring to a
  prior one, not a new class of hidden intermediate record.
- The user sees both D and F, which is exactly the comparison the story's own
  human evaluation has to collect anyway.

The draft asserts that D must not reach the user but does not argue why seeing a
candidate and then a revision is worse than seeing only the revision. The cost
of that unargued requirement is the broker, the lifecycle, the diagnostics
store, and the delayed-first-output UX.

The real counter-argument is `voice`: there D is *heard*, and a spoken wrong
answer followed by a correction is worse than a delay. That limits this shape to
`text` and `text_voice` in a first version, which the draft's own open decision 2
already proposes as a text-first rollout. It does not weaken the argument for
text.

This is offered as the shape to compare against the current one before cards 2-6
are written, not as a settled substitute.

## Finding 5: the critic will attack the output contract

The generation prompt carries the output contract for the selected response mode
(canonical canvas, self-contained voice answer, and so on). A critic instructed
to find defects will reliably produce findings about length, structure, and
formatting, and integration will act on them. The canonical canvas drifts, and
the drift will look like the feature working.

The draft has one sentence against this ("do not ... merely rewrite style"), but
the problem is deeper than a prompt instruction, because it contradicts another
stated contract: "all roles receive the same frozen source context". They must
not. The critic needs the request, the constraints, and the source material; it
must not receive the output-contract and persona prompt whose job is to shape
presentation. S is therefore role-filtered, not identical across the three
roles, and that has to be written into the contract explicitly or card 2 will
implement "the same S" literally.

## Finding 6: version slot and sequencing

`roadmap-v1.9-v2.0.md` has no v1.9.2 slot. After v1.9.1 it lists v1.9.x
first-pass canvas prompt experiments, then v2.0. Six task cards introducing a
job lifecycle, a diagnostics store, and new user-facing controls is a minor
version, not a patch. Either renumber, or amend the roadmap in the same commit
as the approved story, per the project rule that a changed architectural
decision updates the planning documents alongside it.

The ordering question against v2.0 (finding 3) also belongs before card 1, not
in a "coordinate this boundary" note.

## Finding 7: a graded ladder, whose middle rung is the shippable minimum

Owner counter-proposal (planning dialog, 2026-09-12): make this a graded axis
with three rungs rather than one feature with an on/off switch.

1. Today's single pass, unchanged.
2. **ReThink** - two sequential independent contexts. Pass 1 is the ordinary
   turn. Pass 2 is framed in the first person: the request, the model's own
   draft, and one chance to revise before the answer is sent.
3. **Review** - the drafted three-pass generation, critique, integration.

This is a better structure than draft 1, for three reasons, only one of which is
cost.

**The two rungs have opposite biases, and rung 2's bias may be the correct
one.** A critic instructed to find defects has a null action it is not offered:
its instruction-following incentive is to produce findings whether or not any
exist. A first-person revision has a natural null action - send the draft as it
stands. Rung 2 therefore trades "invents objections" for "defends its own
draft", which is the ownership bias that makes self-correction weak.

Which trade is better depends on the base rate of defective answers. If most
answers are sound, rung 2's bias agrees with the truth most of the time and
rung 3's contradicts it most of the time. That inverts the reading of the
ladder: rung 2 is not a weakened rung 3, it is the candidate default, and rung 3
is the tool for a turn the user already suspects is wrong and will pay an
adversarial pass for. Draft 1 assumed the opposite ordering without arguing it.

**Rung 2 removes most of draft 1's open decisions rather than deferring them.**
It has no critique format (open decision 4 disappears), no findings schema, no
integration arbitration, and no version of finding 5: a self-revision inherits
the output contract legitimately, because the revision is what produces the
final canvas. What remains is one prompt and one extra dispatch, structurally
identical to `run_derivative_pass()`. Rung 3 keeps every one of those questions.

**It sharpens the evaluation instead of diluting it.** Rung 3 then has to beat
rung 2 at roughly 1.5x its cost, not beat a single pass. The evaluation card
gains one arm and becomes more decisive.

Three constraints on the ladder:

- **The first-person framing must be a labeled artifact, not a fabricated turn.**
  Draft 1 already forbids the wrong implementation ("never added as authentic
  prior dialog turns"), and the owner's phrasing reads as narration rather than
  a synthetic `assistant` message, but the lazy implementation is a message list
  containing the draft as an `assistant` turn, which the model cannot then
  distinguish from real history. Pin this in the contract; the safe shape
  already exists in `run_derivative_pass()` (system carries the contract, user
  carries the text).
- **"Thinking mode" is the wrong name for the axis** regardless of what the
  rungs end up called. `ReasoningLevel` (off/low/medium/high,
  `src/jarvis/dialog/thinking_mode.py:36`) is already the graded mental-effort
  knob. The new axis is how many independent revisions an answer gets, not how
  hard the model thinks. Naming is deferred, but these two must not collide in
  config and documentation.
- **A third axis costs test surface.** 3 response modes x 4 reasoning levels x
  3 rungs is 36 combinations, and draft 1's acceptance criteria already demand
  coverage of "all response-mode combinations". The reworked story must say
  which combinations are meaningful and which are refused at config validation.
  Two are suspect on their face: `voice` + rung 3 is a very long silence with no
  sign of life, and rung 2 + `reasoning=high` probably pays twice for one thing.

## Smaller notes

- **Open decision 4 (critique format):** structured findings with schema
  validation is the fragile option for a 12B local model. Bounded prose with the
  integrator as the consumer is more robust, and the integrator is a model, so it
  does not need a parser. Do not build a validator before the evaluation shows
  the model can hold a schema under load.
- **Open decision 6 (diagnostics durability):** for an evaluation card, raw role
  outputs belong in scratchpad files. Designing storage, retention, and an
  inspection UI before the feature is known to ship is work the go/no-go may
  discard.
- **Open decision 7 (quality gate):** the rubric must be a number agreed before
  the evaluation runs - how many corrected errors against how many introduced
  errors, over how many independent cases, makes this worth its latency.
  Deciding afterwards means judging a sunk cost by feel. The draft is right to
  refuse to invent the number; the owner still has to set it before card 1.
- The draft's statement that a reviewed `text_voice` turn is "three
  reasoning-role passes plus one spoken-rendering pass" is correct and belongs in
  front of the latency discussion, not after it. At the recorded ~87 tok/s
  generation plus prefill over a large frozen packet repeated three times, this
  is a several-times-longer turn, and under the current foreground-wait proposal
  Jarvis is silent for all of it.

## Appendix A: minimal plan for rung 2 (ReThink)

Grounded in the current code: model options are assembled in `build_payload()`
from the single `BackendSettings` instance
(`src/jarvis/dialog/backend.py:95`, `_OPTION_FIELDS` at line 45), with no
per-request override; `config.toml:18` sets `temperature = 0.123` with
`top_p = 0.9`, `top_k = 50`, `min_p = 0.05`, `repeat_penalty = 1.025`; `seed` is
unset in `config.toml` and only a commented example in `config.example.toml:34`,
so every call today runs on a random, unrecorded seed.

### Static

**Prompts.** Two, and only the second is new. Pass 1 is today's turn with no
change at all - otherwise it is unclear what the comparison measures. Pass 2 is
`system` = the revision instruction, `user` = the source packet, plus a
separately labeled `user` block carrying the draft.

The revision instruction needs exactly four things: the grounds that justify a
change (request misread, constraint lost, unsupported claim, caveat dropped,
arithmetic or reasoning error); an explicit ban on rewriting style, length, and
structure; the output contract of the active response mode; and an explicit null
action.

**The null action is this rung's main design decision, and it has a price.** If
"no change needed" means re-emitting the draft verbatim, the null case pays a
full generation to echo itself - at the recorded ~87 tok/s (`PROJECT.md:61`)
roughly 7 s for a 600-token answer. A sentinel first line lets the runtime reuse
the draft instead, but a sentinel is parsing, and parsing is the malformed-output
risk this file argues against elsewhere. Suggested compromise: accept both, and
treat any output that is not the sentinel as the complete final answer - a check
on one line, the smallest contract available. Decide before the card, because
both the cost model and the failure path depend on it.

**Fixed model parameters.** Locked across passes: `model`, `num_ctx`, `top_p`,
`top_k`, `min_p`, `repeat_penalty`. Varying them multiplies the experiment space
without any hypothesis about mechanism. Allowed to differ by pass: `temperature`,
`seed`, reasoning level. Reasoning defaults to `off` on both passes on the
finding-1 evidence; `high` on the revision pass is one arm of the evaluation,
not a shipped setting.

This implies the one real code change: `build_payload()`/`iter_chat()` must
accept a per-pass options override. Today the only way to vary an option is to
substitute the whole `BackendSettings`, which is the wrong seam. Small, but it
belongs in the card rather than being discovered mid-implementation.

**Five decisions draft 1 needs here that a prompt does not cover:**

- *Eligibility.* Text only in the first version. A turn carrying an image or
  audio with the rung enabled must be visibly not revised, not silently pass the
  revision by - a silent skip is exactly the dishonesty draft 1 forbids.
- *Budget.* The check that source packet plus draft will fit has to happen
  before pass 1, not before pass 2. Otherwise the answer is generated and only
  then found unrevisable.
- *Failure and interrupt.* This rung has a freedom rung 3 lacks: the draft is a
  complete answer produced by the ordinary path. On timeout, error, or interrupt
  during the revision, shipping the draft marked "not revised" is honest. It
  does not violate draft 1's "failure cannot silently promote D" - the load-
  bearing word there is *silently*, and an explicit mark is not a silent
  promotion.
- *Journal.* One event; the draft stored as a collapsed block excluded from
  retrieval; the revision is `event.text`. This is the mode-3 spoken-derivative
  pattern reused. Check whether `provenance.py` already has a suitable source
  kind or needs one added - small, but real scope.
- *Activation.* One persistent flag, default off, applied to the next accepted
  turn, latched per job. Copy `ReasoningLevelState` including its
  read-decide-write-without-await rule (`src/jarvis/dialog/thinking_mode.py:63`).
  No new UI mechanism.

### Dynamic

Almost nothing should be dynamic, deliberately. The only genuinely per-turn
quantity is the budget reservation for the draft, whose size is unknown until
pass 1 finishes.

Two candidates are rejected: deciding per turn whether a given answer is worth
revising is the deferred automatic-difficulty judgment draft 1 places out of
scope, and a `num_predict` ceiling derived from the draft's length risks
truncating a legitimately longer correct answer.

A feature whose parameters wander between turns cannot be measured, and
measurement is the entire purpose of the first card. Sampling diversity comes
from `seed`, not from drifting settings - and `seed` must start being set and
recorded regardless of this rung, since without it no evaluation run is
reproducible.

### The temperature question, resolved as a measurement rather than a setting

Two parametrizations were considered and both rejected. An absolute delta around
the current value (the owner's first proposal, +/- 0.25) is malformed: the base
is 0.123, so the lower bound is negative. A percentage of the current value (the
owner's second proposal) fixes the sign but introduces two worse problems.

First, accidental coupling: `temperature = 0.123` is a generation setting tuned
for ordinary answers, and a multiplier makes the revision temperature a function
of it, so a later change to generation quality silently retunes the revision.
The project has met this shape before and resolved it the other way - `num_ctx`
and `prompt_capacity_tokens` are coupled through an explicit startup
`ConfigError`, not through implicit derivation (`PROJECT.md:63`). Two absolute
values plus a validation rule is the consistent choice.

Second, a multiplier does not preserve the intent across the range. If the
intent is "the revision is somewhat freer than the generation", a base of 0.123
needs a factor around 3 to 5 to leave the near-greedy regime at all - and a
factor of 3 applied to a base of 0.5 gives 1.5, which is incoherent. The
invariant the owner wants is not expressible multiplicatively at any
coefficient.

There is also a narrower doubt: +/- 50% of 0.123 spans 0.06 to 0.185, and both
ends are still effectively argmax, so the predicted outcome is an echo rather
than a different sample. That is a prediction, not a finding, and it does not
need to be argued - it needs to be measured, and the measurement is cheap.

**Therefore: no temperature setting in the first card.** Make it step 0 of the
evaluation instead. Take 15-20 existing answers, run the revision pass at the
current temperature, and see whether it changes anything at all. Three outcomes,
each closing the question:

- never changes anything - temperature is the blocker, and an absolute revision
  value gets chosen from data;
- changes things and mostly makes them worse - the rung is dead, learned at the
  lowest possible cost;
- changes things and sometimes improves them - temperature is not the
  interesting variable; keep one value for both passes and add no parameter.

Two of the three outcomes mean the setting is never needed. Introducing it now
would spend config surface, validation, and documentation on an option that is
probably unnecessary.

If a spread is wanted as a spread rather than as a different value, the
mechanism is `seed`: already supported, already effectively random, and needing
only to be recorded.

## Proposed reduction

1. One throwaway evaluation card. A standalone script against Ollama; no Jarvis
   integration, no production wiring.
   - Step 0: does a revision pass at today's settings change the draft at all
     (appendix A). This gates everything after it and costs almost nothing.
   - Then four arms: single pass at today's defaults; single pass at comparable
     compute; rung 2 with per-pass reasoning asymmetry; rung 3. Cases from the
     draft's Verification section. Record raw role outputs, effective options
     including the seed, timings, corrected errors, and introduced errors.
2. Owner sets the stop rule numerically before that card runs - how many
   corrected against how many introduced errors, over how many independent
   cases, justifies the latency. Set separately for rung 2 and rung 3, since
   rung 3 must clear a higher bar than rung 2 (finding 7).
3. Implement rung 2 only, per appendix A, if it clears its rule. Decide between
   draft 1's pre-emptive shape and finding 4's on-request shape at that point,
   with the data in hand.
4. Write rung 3's cards only if rung 3 beat rung 2 in step 1. Until then it stays
   a hypothesis, and none of its open decisions - critique format, findings
   schema, integration arbitration, diagnostics storage - needs an answer.

## Draft 2 review (2026-09-12)

Draft 2 closes findings 1-7. It is a materially better document: the ladder is
the organizing structure, the evaluation is one disposable card with a
pre-approved numeric gate, the broker is reduced to a typed seam with job
ownership separated from compute arbitration, and the honest-outcome rules for
failure, cancellation, and ineligibility are stronger than what finding 4 or
appendix A proposed.

### Corrections draft 2 made to this file

Recorded because three of the five would have mis-designed the evaluation:

1. The reasoning A/B is task v1.8.0-22 (annotation generator), not v1.8.0-3.
   Fixed in findings 1 and 2 above.
2. Finding 4's "roughly half the cost" framing is wrong. On-request review
   spends two *additional* passes but three in total, because the published
   answer was itself a generation. Draft 2 is right to forbid fixed half-cost
   and 1.5x claims and to require measured token/prefill costs instead.
3. Appendix A proposed settling the sentinel/echo contract before measurement.
   Draft 2 reverses the order: measure the real echo cost first, and evaluate a
   reuse marker separately only if that cost proves material. Better - the
   compromise was optimizing a case whose price was unmeasured.
4. Appendix A's step 0 inferred "no change means temperature is the blocker".
   That inference is unfounded, and draft 2 states why: an unchanged answer can
   mean correctness, an ineffective instruction, an unseen error, or
   insufficient variation. Step 0 remains worth running as a feasibility pilot;
   its three-outcome reading in appendix A does not survive.
5. Finding 5 over-corrected. Withholding the output requirements from the critic
   would make it attack legitimate format as a defect. Draft 2's split -
   legitimate output requirements yes, persona and presentation instructions no -
   is the correct boundary.

## Finding 8: the two-pass branch lost its framing, and framing is its mechanism

Draft 2's "Two passes: generation and self-revision" specifies "a revision
instruction" over "a labeled D" in neutral third person. The owner's original
formulation was first person: the request, *my* draft, and one chance to revise
before sending.

That framing was the whole basis of finding 7's claim that the two rungs have
opposite biases. A model shown its own draft as its own has a cheap null action.
A model shown "here is a candidate, identify what to fix" is a critic with edit
rights, and inherits exactly the manufactured-findings incentive that makes the
three-pass rung suspect. Draft 2 keeps the *permission* to retain the candidate
("Retaining D is a valid outcome") but not the framing that makes exercising it
natural.

Consequence: the most interesting variable in the two-pass branch is now
unspecified. Evaluation arm 3 varies reasoning asymmetry only; nothing declares
whether the revision prompt is first-person self-revision or third-person
candidate review.

Resolve it explicitly, one of two ways: declare the framing a fixed constant
with a stated reason, or make it a second variant inside the two-pass arm.
Recommendation: make it a variant. It costs one additional prompt, it varies a
mechanism rather than a setting, and unlike temperature it has a stated causal
story about why the outcome should differ.

## Finding 9: the binding constraint is owner hours, and the story does not name it

Four arms, multiple seeds, five case categories, repeats, plus a feasibility
pilot. Every live run is human-executed under the testing protocol. GPU time is
cheap; supervised owner time is the scarce resource, and draft 2 budgets
everything except that.

Gate 1 requires owner approval of case count, repeat count, and criteria, but
not of total size, so the card will be sized by whoever writes it and the
constraint will be discovered during execution.

Recommendation: gate 1 also fixes a maximum human-time budget for the whole
evaluation. If the design does not fit, arms get cut - the fix is a narrower
experiment, not a longer run. This is also the honest place to decide that the
three-pass arm may be deferred, since it is the most expensive arm and the one
with the weakest prior.

## Finding 10: blinding will fail; pre-declared per-case rubrics are the substitute

"Where practical, score final answers without revealing their experimental arm"
will not hold in practice. A three-pass integrated answer differs from a
single-pass answer in length and structure, so the arm is usually guessable on
sight, and the scorer is the same person who wrote the prompts.

The workable control is not concealment but commitment: a per-case checklist
written *before* any arm runs - constraint X retained, arithmetic correct,
caveat Y present, request not narrowed - filled in per answer. An objective
criterion fixed in advance resists bias better than an attempted blind.

Keep the blinding language as a best-effort, but do not let the evaluation's
validity depend on it.

## Finding 11: "known-correct" needs a second, harder class

Draft 2's case list ("known-correct, known-defective, ambiguous, and
insufficient-evidence") measures sensitivity well and precision poorly.

Injected defects are detectable by construction - draft 2 correctly reports them
separately - and ordinary known-correct answers will mostly be left alone,
producing a reassuring but uninformative regression rate. The damage mechanism
lives in a narrower class: **answers that are correct but look suspicious.**
Counterintuitive arithmetic, a caveat that is legitimately absent, a correct
answer shorter than the question seems to deserve, a refusal to over-qualify.
Those are the cases where an eager critic or a defensive reviser actually
introduces errors.

Add that class explicitly and report it separately from plain known-correct
cases. It is where the no-go signal will come from, if there is one.

## Finding 12: a disposable harness cannot satisfy gate 6

The evaluation card is described as a standalone disposable harness with fixed
fixtures, and gate 6 requires repeating the quality evaluation against the real
integration. Both cannot be true of the same artifacts.

The distinction to write down: the harness code is disposable; the case set,
the injected defects, the per-case rubrics, and the approved numeric criteria
are not - they become the regression set the integrated implementation is
measured against. Say where they live and that they outlive the harness.

## Draft 3 review (2026-09-12)

Draft 3 closes findings 8-12. Three of its choices are better than what this
file recommended, and the improvements are recorded so the reasoning is not lost:

1. The revision framing is chosen on development cases and frozen before
   held-out runs, rather than being a held-out arm as finding 8 proposed.
   Correct: framing selection is prompt tuning, and prompt tuning must not
   happen against the cases that carry the confirmation claim.
2. Deferring the three-pass arm leaves it "unmeasured, not disproved". Finding 9
   leaned on the weak prior as grounds to cut that arm; draft 3 separates budget
   pressure from evidence, which is the honest split.
3. The stress class carries an explicit warning against presenting its
   deliberate oversampling as the ordinary-user regression rate. Finding 11
   asked for the class but not for that guard.

Draft 3 also adds development/held-out freeze discipline, paired comparison over
frozen candidates, and the rule that post-inspection prompt changes start a new
experiment version needing fresh held-out cases. None of that came from this
file, and it is the strongest part of the document.

## Finding 13: the spike reinvents assets and discipline the repository already has

The "Durable evaluation assets" section proposes new locations and re-derives
methodology that exists here, was accepted by the owner, and is closely
analogous. Four concrete precedents:

1. **Harness location.** `manual/` holds 33 human-run scripts invoked as
   `python -m manual.manual_check_*`, each documenting its exact commands and
   why it is not automated. `manual/manual_check_graded_reasoning.py` is the
   closest analogue in the repository: it compares the four `think` values
   against live Ollama across prompt categories - a reasoning-level comparison
   harness. Read it before writing a new one; extending it may be cheaper.
2. **Predeclared-threshold discipline.** `tests/retrieval_benchmark/corpus.py`
   is a fixed corpus with relevance labels and predeclared thresholds, and its
   docstring already states the rule draft 3 derives independently: editing the
   data after seeing a backend's results is a threshold change that must be
   recorded as an explicit revision. `measure_semantic.py` sits beside that
   corpus, which also answers where a measurement script lives relative to its
   fixtures. The proposed `tests/fixtures/answer_revision_eval/` introduces a
   new convention where `tests/answer_revision_benchmark/` would match the
   existing one.
3. **Raw output location.** The repository convention for human-run raw output
   is a gitignored `manual_check_<name>_out/` directory at the root;
   `.gitignore` carries eight of them. Draft 3 proposes
   `scratchpad/v1.9.2-answer-revision/<run-id>/`, and `scratchpad/` is neither
   in `.gitignore` nor present in the tree - so as written, raw runs that may
   contain real conversation text would land on a tracked path. Draft 3 does
   flag "confirm repository ignore behavior", but the path it names is the one
   currently lacking that protection. A session-scoped temp directory outside
   the repository is also unsuitable here: the decision report cites runs by
   hash, and those runs must remain locatable.
4. **`tasks/experiments/`** is a fourth `tasks/` subdirectory, alongside the
   workflow's `tasks/`, `done/`, `bug_reports/` and the de-facto `backlog/`.
   Either keep the protocol beside the spike card in `tasks/`, or add the
   subdirectory to the documented workflow explicitly.

## Finding 14: the case population has no source, and only real usage carries the base rate

Draft 3 forbids presenting the oversampled stress class as the ordinary-user
regression rate, but never names a source from which an ordinary rate could be
estimated at all. Authored cases have whatever base rate their author chose.
Draft 3 itself relies on such a rate - "a tiny gain on an artificial balanced
set may not justify revisions when most ordinary answers are already correct" -
so the claim is load-bearing and currently unsupported.

The data exists: since v1.8.x the Journal is a durable, searchable substrate of
real turns. Recommendation: make case provenance determine which claim a case
can support.

- A sample drawn from real journal history carries the base-rate and
  ordinary-regression claims.
- Authored and injected-defect cases carry sensitivity and stress claims.

Honest limit: real turns usually lack ground truth, so the real-usage sample may
support only "changed / improved / tie / damaged" judgments rather than full
rubrics. That is exactly the measurement the ordinary-rate claim needs, and it
keeps the real-usage sample small.

## Finding 15: the scoring budget sets the case count, not the other way round

In a paired design each case-repetition yields the candidate, one answer per
revision procedure, and the stronger single-pass baseline - roughly four score
sheets. Twenty cases at three repeats is about 240 sheets.

Draft 3 correctly says to estimate human effort from the number of answer sheets
rather than GPU runtime, but the card author will still start from a case count
and arrive at a budget, so the first proposal will not fit and gate 1 becomes a
negotiation. Invert the derivation: fix the scoring budget first, then derive the
maximum case count and repeat count from it. State that inversion in the card's
resource-limits row.

Finding 17 changes this arithmetic substantially but does not remove it.

## Finding 16: a text-quality result does not license `text_voice`

The spike excludes spoken-rendering calls, which is right for a text-quality
question. But the spoken derivative consumes F, and revision predictably changes
F's length, hedging, and structure - precisely the properties the derivative is
sensitive to. Draft 3's own count (2/3/4 passes in `text_voice`) makes the
dependency visible without drawing the conclusion.

Gate 6 covers this implicitly through "repeat quality evaluation on real
integration". Make it explicit: a positive text result authorizes a `text`-mode
slice; `text_voice` requires a derivative check over revised answers before
rollout.

## Finding 17: an external rubric checker is defensible; an external preference judge is not

Owner proposal (planning dialog, 2026-09-12): use an external model reachable
through Ollama Cloud under its zero-day retention policy as the scorer, with
GLM-5.3-Flash as the candidate. Owner context: GLM has been in use for several
weeks as a primary relevance/accuracy filter on fairly complex tasks and has
been satisfactory. That is real operating experience with the model, though not
a measured agreement rate on this rubric's task shape.

**The strongest argument for it is not cost.** Finding 10 concluded that blinding
fails because a human scorer recognizes a procedure by its style. A scorer that
receives shuffled, unlabeled answers and a checklist of binary items is genuinely
blind, and reproducibly so. On the part of the work where the human is
systematically biased, an external checker is methodologically better, not merely
cheaper.

**Runtime locality is not affected, and the contract says so in its own words.**
`PROJECT.md:5-10`: core and inference remain local unconditionally, and this
"does not change based on configuration, testing method, or which components are
enabled". Testing method is excluded from the guarantee explicitly. The project
also already has the category this tool belongs to - graphify is an agent/dev
tool, not a runtime dependency.

Two boundaries to write down, because this is the shape that later gets copied
into runtime code: the scorer module is never imported from `src/jarvis` by any
path, and the card states that this is the first script under `manual/` that
leaves the machine - all 33 existing ones reach only the local Ollama endpoint.

**The real exposure is egress, and it collides with finding 14.** The scorer
receives the request, the evidence, the candidate, and the final answers. If
cases come from real journal history - which is what the base-rate claim needs -
real personal content leaves the machine. A zero-day retention policy is a
contractual promise, not a technical guarantee, and this project treats that
content as sensitive: `/journal/`, `/memory/` and `config.toml` are gitignored,
and draft 3 already forbids committing real conversations as fixtures.

Resolution that keeps both claims: **split scoring by case provenance.**
Authored and injected cases - content the owner wrote - are scored by the
external checker, and that is the large set where the whole load lives.
The real-usage sample stays local and is scored by the human; it is small,
because finding 14 needs only changed/improved/tie/damaged judgments from it.

**Length bias is the technical danger.** Model judges systematically prefer
longer, more hedged, more structured answers, and revision adds hedging and
length by construction. The instrument's bias therefore points in the same
direction as the hypothesis under test - the worst available failure mode,
because it confirms the feature whether or not it works.

Hence a hard format requirement: not "rate the quality" and not "pick the better
answer", but **binary rubric items** - is claim X asserted, is forbidden error Y
present, is caveat Z retained. The task is then close to extraction rather than
judgment, which is also why a cheap tier is defensible on it. Randomize answer
order, and where a comparison is genuinely pairwise, run both orders.

**The scorer must itself be a measured instrument.** The human scores 15-20
sheets directly and agreement is computed, separately for the forbidden-error
items, since those carry the decision. Given the owner's existing experience with
the model this is calibration rather than qualification - it establishes the error
bar that any published regression rate needs, and it can be small. Poor agreement
on the decisive items means the scorer's numbers do not support the gate.

**Reproducibility is weaker than with a local model.** The card requires
recording effective model and digest; a cloud model may expose only a name, and
served weights can change without notice. Practically: score every arm of a case
in one run, record whatever version metadata the API returns, and repeat the
agreement subset at the end - divergence from the start is the drift detector.

**One consequence to see now.** If cloud access is acceptable for scoring, the
question of a cloud *critic* reopens: generator/critic asymmetry is the strongest
available mechanism for the feature (finding 2), and one local model provides
almost none. The locality contract separates the two cases cleanly, because
evaluation is not runtime. Privacy does not separate them - both send
conversation content off the machine. So if the answer on a cloud critic is a
firm no on privacy grounds, the same argument constrains what may be sent to the
scorer, and the provenance split above becomes a requirement rather than a
convenience.
