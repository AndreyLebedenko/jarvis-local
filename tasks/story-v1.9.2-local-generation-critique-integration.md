# Story v1.9.2: Local answer revision and review

**Status:** In Progress.
**Active task:** `task-v1.9.2-1-local-answer-revision-spike.md`.
**Approval:** Story accepted by owner on 2026-09-12; numeric spike protocol awaits its own gate.
**Created:** 2026-09-12.
**Updated:** 2026-09-12.
**Predecessors:** `story-v1.9.0-response-modes.md` and
`story-v1.9.1-provenance-aware-indexing.md`.
**Review input:** `story-v1.9.2-local-generation-critique-integration-notes.md`.
**Planning context:** `roadmap-v1.9-v2.0.md`, `VISION.md`, and `PROJECT.md`.
**Current boundary:** Accepted planning; the active spike card defines preparation and gates. No runtime implementation or live evaluation run,
production configuration change, or later implementation slice is authorized by story acceptance alone.
The filename retains its original identity; product naming remains open.

## Goal and design position

Jarvis should catch material errors before they become a polished answer,
without routinely damaging correct answers or imposing unjustified delay.
Independent local passes are a candidate mechanism, not a correctness guarantee.

Evaluate a ladder of three processing strategies using one local model:

1. Ordinary generation, as today.
2. Generation followed by one independent self-revision.
3. Generation, independent critique, and independent integration.

The ladder expresses different procedures and costs, not increasing confidence
or proven quality. Two passes are a candidate, not a predetermined winner.
Three passes must demonstrate value beyond the cheaper alternatives. If no
additional-pass strategy meets the agreed criteria, retain today's behavior.

The first deliverable is one bounded, disposable evaluation card. Production
cards are written only after its results and the owner's decision. Default
production behavior remains single-pass unless explicitly changed later.

## Weaknesses targeted

- Misreading the task or dropping an explicit constraint during generation.
- Unsupported claims, arithmetic/reasoning errors, and missing caveats.
- A critic inventing objections and an integrator damaging a correct answer.
- Intermediate claims becoming apparent facts through history or retrieval.
- Additional processing hiding its latency, failure, or cancellation outcome.

Review cannot reconstruct absent evidence or reliably repair misunderstood audio
without access to the relevant source. All passes share model weights and may
share blind spots. Agreement is not factual verification. Calculation execution,
source checking, and user clarification remain distinct ways to resolve doubt.
Memory truth maintenance, general prompt-injection protection, and automatic
execution of recommendations are outside this story.

## Evidence and hypotheses

`PROJECT.md` records the owner-run annotation-generator comparison from
2026-08-07 (task v1.8.0-22): reasoning high and off both passed the measured
faithfulness traps, while high took about five times longer. This is evidence
of additional cost without observed benefit on those already-solved cases.
It is not an experiment on independent revision contexts and does not establish
that revision fails. The evaluation needs both genuinely defective and correct
candidates; a ceiling-effect dataset cannot measure correction benefits.

Role framing, the availability of a completed candidate, reasoning level, and
sampling settings are possible sources of useful differences between passes.
No one of these is assumed to be the only mechanism. A critic has permission
to report no findings; self-revision has permission to retain the candidate.
Whether either role nevertheless invents criticism or defends errors is measured.

No conclusion about effective argmax behavior follows from temperature alone.
An unchanged answer can mean correctness, an ineffective instruction, an unseen
error, or insufficient variation. It does not identify temperature as the cause.
Likewise, a changed answer is not evidence of improvement.

## Shared evidence and independent contexts

Freeze an evidence packet E for the accepted task: original request, applicable
constraints, selected history/memory with provenance, permitted source material,
and any already-collected evidence. Record the relevant time and configuration.

Evidence is shared; system prompts are role-specific. Do not copy an identical
whole system prompt into every role. Separate source facts and user requirements
from persona and presentation instructions. The critic needs to know legitimate
output requirements to avoid mistaking them for defects, but is not instructed
to speak in the final persona or optimize presentation.

Each pass gets a separately constructed request. Candidate and critique are
explicitly labeled artifacts, not fabricated prior conversation turns. There is
no mutable chat context shared between roles. Only explicit task outputs cross
passes; Ollama `message.thinking` never crosses into subsequent input, answer
events, journal content, diagnostics, or TTS.

## Strategy contracts

### Single pass

Today's generation payload and behavior are the baseline. Do not improve its
prompt only for the multi-pass arms or quietly weaken the baseline. Preserve
original constraints, evidence, and final response-mode requirements across arms.

### Two passes: generation and self-revision

Generation over E produces candidate D. A separate revision context receives E,
a labeled D, and a revision instruction, producing final answer F.

The instruction permits changes for material defects: misunderstood request,
lost constraint, unsupported assertion, reasoning/calculation error, or omitted
caveat. It discourages gratuitous changes to style, length, and structure, while
allowing changes needed to fix a substantive error or meet an explicit user
requirement. It preserves the active final-output contract.

Retaining D is a valid outcome. Start the evaluation with complete final-answer
output, including unchanged output, and count its real generation cost. Do not
introduce a sentinel protocol before measurement just to make the null action
look cheap. If echo cost proves material, evaluate a reuse marker separately,
including malformed output, literal-marker content, buffering, and failure
semantics, before approving production parsing.

First-person framing ("my draft, one opportunity to revise before sending")
is an explicit candidate prompt, not an implicit property of the word revision.
Compare it with neutral candidate editing on development cases, holding evidence,
candidate, reasoning, and sampling settings constant. Both prompts permit no
change and use labeled artifacts, never fabricated conversation turns. A reduced
incentive to invent edits is a hypothesis to test, not a proven ownership effect.
Choose the framing before held-out evaluation; do not cross every framing with
every reasoning setting unless the approved run budget explicitly includes it.

### Three passes: generation, critique, integration

Generation over E produces D. Critique over E and D produces C. Integration over
E, D, and C produces F, following the selected final-output contract.

Critique identifies concrete defects and their grounds, distinguishes missing
information from errors, and can report no material findings. Initially use
bounded prose for the experiment; structured findings are not a prerequisite.
Integration accepts supported criticism, rejects unsupported objections, preserves
correct content, and exposes unresolved uncertainty rather than inventing agreement.

One cycle only. No recursive review, repeated critique until agreement, or
unbounded retries. Integration still runs when C has no findings in this arm.

## Delivery shape is a separate decision

Recommended initial experiment: revision before publication, for both multi-pass
arms. D and C remain hidden from ordinary answer surfaces; F is canonical.
This directly tests the proposed error-prevention benefit.

An alternative is review requested after a normal answer has been published.
Then D is already a legitimate canonical answer; F is a new, explicitly linked
revision, never a rewrite of old journal text. This protects normal first-answer
latency and lets the user choose which answers warrant more work, but does not
prevent the initial error from being seen or heard.

On-request review reuses a completed generation; it does not eliminate its cost.
A normal answer followed by critique and integration still totals three passes.
Costs depend on actual tokens, prefill, and reasoning; avoid fixed half-cost or
1.5x claims. On-request review also needs original evidence, not merely the old
answer. Media/tool eligibility and evidence retention remain design questions.

Choose the production delivery shape after evaluation and before implementation
cards. Do not build both by default or mix their canonical-history contracts.

## Evaluation card and go/no-go

Prepare a standalone local harness and fixed fixtures; no Jarvis runtime wiring,
new scheduler, diagnostics database, settings UI, or runtime cloud adapter. Outputs belong
in the artifact locations defined below. The human runs live Ollama and
hardware-dependent checks under `AGENTS.md`. One human-started script may run a
batch; the protocol does not require manual dispatch of each model request.

### Spike extraction contract

The next card must answer one bounded question: does either tested revision
procedure improve final-answer quality enough to justify its measured cost on
the declared text-task population? It does not establish a universal accuracy
claim, choose production UI, or prove future cloud/broker behavior.

The card author prepares these concrete items for owner review before live runs:

| Required item | What must be fixed |
| --- | --- |
| Question and scope | Text-only source evidence, task categories, exclusions, primary comparisons |
| Case manifest | Stable case IDs, category, provenance, development/held-out split, independent case counts |
| Per-case rubric | Required facts/constraints, allowed alternatives, forbidden errors, severity, reference answer or checkable justification |
| Run matrix | Exact role prompts/options, seeds, repetitions, arms, comparisons, and maximum total backend calls |
| Numeric decision table | Minimum gain, maximum regression, critical-error rule, latency/cost bands, minimum evaluable cases, incomplete-run handling |
| Resource limits | Fix owner setup/scoring budgets first, including checker calibration and audits; derive case/repeat counts from them; cap machine runtime and cloud calls/cost |
| Execution handoff | Exact commands, dependencies, input/output paths, effective configuration capture, and safe stop/resume behavior |
| Deliverables | Versioned inputs, raw permitted outputs, completed score sheets, summary and explicit next-step recommendation |

All cells must have concrete values in the card before execution. Numbers are
proposed by the card author with a count/time estimate and approved by the owner;
the story does not invent quality thresholds or ask the executor to improvise
them. Case rubrics are written before seeing arm outputs. Answers without a
defensible rubric may be exploratory examples, not scored gate evidence.

Budget backend calls explicitly: sum(case count x repeats x calls per strategy)
plus declared pilot variants. Count any spoken-rendering calls separately; they
are excluded from this text-quality spike unless explicitly added. Estimate human
scoring from the number of answer sheets, not GPU runtime. The pilot measures
actual runtime and scoring effort. If the planned evaluation does not fit, return
a smaller concrete matrix for approval rather than silently extend it.

The three-pass arm may be deferred under an approved reduction, but then its
effectiveness is unmeasured, not disproved. Retain the baselines needed for every
remaining claim. No full factorial parameter search or automatic extension until
a positive result appears.

### Repository conventions and durable evaluation assets

Read `manual_check_graded_reasoning.py` and `tests/retrieval_benchmark/corpus.py` before designing the harness and corpus. Reuse suitable conventions without mixing unrelated script responsibilities. Locations to make concrete in the spike card:

- `tests/answer_revision_benchmark/`: sanitized case manifest, separate
  development and held-out case files, injected-defect definitions, and rubrics.
- Documents beside the spike card in `tasks/`: approved protocol and thresholds,
  frozen prompt variants, version/hash manifest, score-sheet template, and
  sanitized baseline results and decision report.
- `manual/manual_check_answer_revision.py`: human-run entry point using the
  existing `python -m manual.manual_check_*` convention.
- `manual_check_answer_revision_out/<run-id>/`: durable local raw run outputs.
  Add and verify an explicit root-output ignore rule before writing any payload;
  do not commit real personal conversations or credentials as fixtures.

The harness is replaceable. Cases, rubrics, prompts, criteria, score sheets and
sanitized reference results survive it and are versioned together. Reports name
raw run locations and hashes; deleting a harness must not delete its evidence.
These files are passive fixtures, not live-Ollama tests collected by pytest.
Later production verification reuses them through an integration adapter, with
an explicit record of any changed conditions rather than a new untracked dataset.

### Case provenance and real-usage claims

Authored and injected cases support controlled repair and stress claims. Estimate
ordinary-use outcomes only from a local Journal sample selected by a predeclared
rule: period, eligible turn types, exclusions, and random or systematic selection.
Do not cherry-pick interesting mistakes. Preserve the original source evidence
needed for replay; record unavailable evidence and exclusions explicitly.

The human scores this real-usage sample locally: improved, tied, damaged, or
not assessable, with a short reason. Change detection is recorded separately;
a change is not automatically an improvement. Without defensible ground truth,
these are human comparative judgments, not verified accuracy measurements.
Report denominators and unassessable cases. Limit conclusions to the sampled
period and request population; a small convenience sample does not establish
a universal base rate. Keep this sample separate from authored gate fixtures.

### Spike-only external rubric checking

Owner-approved direction: use GLM through Ollama Cloud for preliminary rubric
checking in this spike only. GLM-5.3-Flash is the candidate named in the review;
verify its exact available API model identifier before fixing the card. Do not
substitute another model silently or assume a local model digest is available.
The local generation/revision procedures remain the objects being measured.
No cloud critic, integration pass, or Jarvis runtime dependency is introduced.

Use three scoring layers:

1. Pure code checks properties it can verify reliably, such as exact constraints
   and fixture calculations, without brittle wording-based semantic judgments.
2. GLM checks remaining predeclared rubric items on approved nonpersonal cases.
   Each item returns satisfied, violated, or unclear, plus a supporting answer
   excerpt and a brief reason. It does not choose the most attractive answer.
3. The human scores calibration cases, disputes, serious detected defects, and
   a random sample of answers the checker passed. The last category detects
   missed defects. Real Journal examples remain local and human-scored.

Authorship is not an egress permission. Inspect authored/injected fixtures for
personal content before including them in an explicit cloud-eligible manifest.
The cloud checker receives only the necessary approved request/evidence, rubric,
and answer. It never reads Journal, memory, credentials, or live configuration
as case data. It has no tools; candidate text is untrusted evaluation material.
No automatic Journal-to-cloud route or automatic fallback to cloud scoring.

Ollama's privacy policy, checked 2026-09-12, states that cloud content is processed
transiently, not retained beyond fulfilling the request, and not used for model
training; service/account metadata is separate. Source:
https://ollama.com/privacy . Record the applicable policy reference/date in the
protocol. This is a provider commitment, not a guarantee that data never leaves
the machine. The scorer is an explicitly external developer tool. Its module
must not be imported directly or transitively by `src/jarvis`; keep credentials
out of payload artifacts and fixtures. The manual handoff must explicitly name
this network boundary instead of inheriting the local-only expectation of other
manual checks. Nothing here authorizes agent-run live calls in this story turn.

Shuffle answers and hide strategy labels. This reduces direct label bias but
does not eliminate style/length bias or make GLM inherently more impartial than
the human. Use item-level rubrics, allow uncertainty, and run both orders where
a genuinely pairwise comparison is needed. Validate checker responses; malformed
or unsupported assessments are unscored/escalated, never implicit passes.

Calibrate against human judgments on both defects and correct answers, including
correct-but-suspicious cases. Separately report missed defects and false defect
reports, especially on gate-critical items; aggregate agreement alone can conceal
a checker that passes everything. A 15-20-sheet pilot may estimate feasibility,
but cannot automatically justify a low error-rate claim. The card sets numeric
checker acceptance rules, audit volume, and critical-item handling before runs.
If checker reliability does not meet them, its scores cannot support the gate:
return to the human budget, reduce the matrix by approval, or mark inconclusive.
Do not let GLM's self-reported confidence authorize its own score.

Freeze checker prompt/options with the experiment. Record available model/version
metadata, timestamps, exact submitted packets, raw verdicts, and human overrides.
Score all arms of a case close together and repeat the calibration subset at the
end to look for drift. Missing provider version information is an explicit limit;
a stable alias or seed does not prove stable cloud weights. Count calibration,
audits, disputed items, cloud calls/cost, and end checks in the resource budget
before deriving the case count. Cloud checking reduces human work; it does not
remove human validation or authorize expanding the run without a new budget.

### Development, freeze, and held-out evaluation

Use development cases for the feasibility pilot, prompt/framing choice, and the
limited reasoning variants. Freeze selected prompts, options, scoring rules and
the final matrix before opening held-out outputs. Held-out cases are disjoint
from development cases; near-duplicate variants of one problem stay in one split.
The evaluator may know their rubrics, but must not use their arm outputs to tune
the procedure.

The held-out set includes ordinary correct answers and a separate class of
correct-but-suspicious answers: counterintuitive but justified results, warranted
brevity, and legitimately absent caveats. Supply a checkable justification for
their correctness. Report this stress class separately; do not present its
deliberate oversampling as the ordinary-user regression rate.

Use a paired comparison where possible: both revision procedures receive the
same frozen natural candidate for a case/repetition. Report shared-generation
savings in experiment runtime separately from the full cost a user would pay
for each strategy. Injected-defect repair remains a separate diagnostic exercise.

After held-out results are inspected, prompt changes start a new experiment
version and require fresh held-out cases for a new confirmation claim. Reusing
old cases for regression is useful but does not restore their held-out status.

Before running, obtain owner approval of numeric criteria: independent case count,
repeat count, minimum material improvement, maximum introduced-error rate,
severity weighting or critical-error veto, and acceptable latency/cost. Define
criteria separately for two and three passes. No post-hoc threshold changes to
justify implementation. Insufficient evidence can mean a bounded follow-up
experiment, not automatic success or definitive rejection.

Evaluation arms:

1. Single pass at current effective settings.
2. Single pass with increased reasoning/generation allowance at a comparable
   measured cost or latency budget.
3. Two passes; start with existing settings, then test a predeclared limited
   reasoning-asymmetry variant, such as generation off / revision high.
4. Three passes, with declared per-role reasoning settings; compare against
   both the two-pass arm and the stronger single-pass baseline.

Exact wall-clock equality cannot be assumed from a reasoning label. Record actual
cost/latency and compare within agreed bands; do not truncate one arm's answer
just to force equality. Freeze model identity and unrelated sampling parameters.
Temperature changes require a stated hypothesis and a separate controlled arm,
not a new production setting by default.

Record effective model/digest, prompt versions, complete permitted evidence,
options, explicit seeds, stage outputs, output lengths, completion outcomes,
and stage/total latency. Repeat with multiple seeds and independent cases.
Seeds improve experimental control but do not promise bit-identical GPU runs.
The harness may set per-call options without requiring a production backend API
change. Add production overrides only if the chosen design actually needs them.

A small pilot may check prompt behavior and harness feasibility; it cannot conclude
that unchanged output is a temperature defect or that a handful of regressions
settles all strategies. Include known-correct, known-defective, ambiguous, and
insufficient-evidence cases, plus output-contract and caveat-preservation traps.
Use both natural generation and labeled injected-defect cases; report these
separately rather than treating injected cases as the real error base rate.

Lead the report with introduced errors and their severity, then corrected errors,
remaining errors, unnecessary edits, and latency. Distinguish conditional repair
rates from whole-answer end-to-end quality. A tiny gain on an artificial balanced
set may not justify revisions when most ordinary answers are already correct.
Where practical, score final answers without revealing their experimental arm.
Shuffle answers and hide arm labels as an additional bias control, but do not
depend on perfect blinding: style may reveal the procedure. Predeclared per-case
checklists are the primary scoring control. Record ambiguous scoring explicitly;
do not invent a favorable interpretation after seeing which arm produced it.

The decision report must choose one of: qualifies for a stated production slice;
does not meet the agreed gate in this tested scope; or inconclusive/deferred.
Include denominators, case-level outcomes, severity and timing summaries, and
uncertainty appropriate to the sample. Repeats of one case do not count as new
independent tasks. Stop at the approved budget. Any follow-up needs its own
bounded question, matrix and approval; an inconclusive result does not authorize
implementation or an open-ended investigation.

Production recommendation follows the measured quality/cost trade-off. Three
passes need incremental value over two passes; two passes need value over both
single-pass baselines. A strategy may qualify for a bounded class of requests
without qualifying as a universal default. The owner decides the rollout.

## Production boundary, conditional on a successful evaluation

### Foreground execution and future broker

Reuse existing turn cancellation and backend dispatch where their contracts fit.
`run_derivative_pass()` is a precedent for a separate prompt and reasoning level,
not proof that internal review completion can use ordinary final-answer handlers.
`on_response_complete()` currently updates history and schedules speech; internal
stages must not accidentally trigger those effects. `speak_streaming=False` alone
only suppresses speech, not screen publication or memory writes.

Keep pass execution behind a small typed boundary: immutable inputs, cancellation,
stage results, and one terminal outcome associated with the owning turn. Do not
make UI waiting or a spoken acknowledgement own execution. This preserves a seam
for later broker-managed work without implementing a durable queue now.

A broker's job ownership and a scheduler's compute arbitration are distinct
responsibilities. The roadmap's v2.0 idle-time queue should eventually share an
explicit ownership/arbitration contract with foreground work. Do not create a
second scheduler here, or require that future queue merely to run sequential
foreground passes. Detached conversation and durable recovery remain later work.

### Eligibility, budgets, and actions

Proposed first scope: text requests with available text evidence, without tool
execution inside revision/critique/integration. Resolve tool-dependent turns
explicitly before enabling them; ordinary generation may currently perform side
effects, and reviewing its text afterwards cannot undo those actions.

If a request is ineligible, communicate that outcome before processing it as an
ordinary answer under the approved policy. Do not label a skipped pass successful.
A text-only first scope concerns input evidence, not exclusion of voice output.
Audio/images need their own approved evidence packet design; use existing
`images` transport and the corrected short-audio facts in `PROJECT.md`.

Preflight reserves for every assembled pass, including candidate and critique,
before generation. Also validate actual artifact sizes at stage boundaries.
Unknown output length means preflight alone cannot guarantee fit. Define bounded
artifacts and explicit overflow behavior; never silently drop original constraints
or truncate a potentially correct revision to the draft's length.

### Output and provenance

Processing strategy, `ReasoningLevel`, and `ResponseMode` are separate axes.
Naming, activation, persistence, and per-role settings remain owner decisions.
Default off/single-pass is proposed. Latch effective settings at turn acceptance.
Do not reject combinations merely because they might be slow; measure them and
restrict only combinations with an explicit unsupported contract.

For pre-publication delivery, only F is canonical. If diagnostic D/C retention is
approved, keep it outside recent dialog, retrieval, annotation input, and memory.
A collapsed UI block does not itself ensure that exclusion. Prefer existing
storage/provenance mechanisms where suitable; a new store is not assumed.

For on-request delivery, preserve D as its original canonical turn and link the
new revision to it. C stays diagnostic. The user can distinguish the revision
from the original; no retroactive journal rewriting.

For either shape, `text` and `voice` keep their final output requirements.
`text_voice` runs the existing reasoning-off spoken derivative over exact F.
Total model passes are therefore 2/3/4 for single/two/three-pass strategies in
`text_voice`, versus 1/2/3 without that derivative. Stage progress should make
the wait intelligible; spoken acknowledgement is optional pending UX review.

### Failure is different from cancellation

A failed revision may offer an explicitly unreviewed D, if the owner approves
that fallback. It must never silently publish D as reviewed. This is a product
choice, not an automatic consequence of D being a complete candidate.

User cancellation stops further processing and must not automatically publish
or speak an unpublished candidate. A previously published answer stays in history.
If final streaming has begun, retain existing honest partial-answer semantics.
Timeout, malformed/empty output, overflow, and cancellation have distinct outcomes.
Late results cannot publish after cancellation, duplicate an answer, or change
another turn. No hidden retries or automatic restart resumption in this scope.

## Ordered work and decision gates

1. **Approve evaluation design.** One bounded evaluation card with source cases,
   arms, numeric criteria, exact human-run commands, and artifact locations.
   Satisfy the spike extraction table, including owner-time limits, per-case
   rubrics, split discipline and estimated backend-call count. Resolve evaluation
   questions only; do not predesign every production feature.
2. **Run and assess the evaluation.** Human executes local inference; inspect
   results and record limits. Select single-pass retention, a qualifying strategy,
   or a specifically bounded follow-up. No production wiring before this gate.
3. **Approve the production slice.** Select strategy, delivery shape, eligible
   requests, output/fallback protocol, prompts/settings, diagnostics policy, and
   UX. Align the approved v1.9.2 scope with the roadmap. If scope is too large,
   split it with owner agreement; the requested version is not rejected merely
   because an arbitrary task count resembles a minor release.
4. **Implement the selected contracts and foreground execution.** Create focused
   task cards for payload/budget policy and orchestration using pure tests and
   fake executors. Do not implement the entire ladder if only one extra strategy
   qualifies. Stop if reuse requires an unapproved broad orchestrator redesign.
5. **Integrate output, controls, and provenance.** Add the approved user surface,
   journal behavior, failure/cancellation handling, and response-mode integration.
6. **Document and verify release.** Update `PROJECT.md` alongside actual approved
   architectural changes, user/config docs and roadmap as appropriate. Prepare
   self-sufficient human checks and repeat quality evaluation on real integration.
   Stop for human review before closing, committing, or merging task work.

Three-pass implementation cards are conditional, not owed merely because the
story began with that proposal. This draft changes no settled project contract.

## Acceptance criteria

### Evaluation gate

- [ ] Existing manual/benchmark conventions are used; the raw-output ignore rule
      is verified before any payload is written.
- [ ] Journal sampling is predeclared and local-only; authored/stress and real-use
      judgments have distinct denominators, provenance, and claim boundaries.
- [ ] Cloud checking is restricted to the approved nonpersonal manifest, isolated
      from runtime imports, and documented with provider/model/policy metadata.
- [ ] Code/GLM/human scoring responsibilities, checker calibration thresholds,
      false-negative/false-positive measures, random pass audits, and drift checks
      are fixed before runs and included in the owner-time and cloud budget.

- [ ] Cases, repeats, scoring, severity rules, cost bands, and numeric stop/go
      criteria are owner-approved before live evaluation.
- [ ] The card fixes owner setup/scoring time, machine runtime, call ceiling,
      pilot allocation and reduction rules; no silent budget expansion occurs.
- [ ] First-person and neutral revision framing are compared on development
      cases or one is explicitly fixed with a stated reason. Held-out runs use
      frozen prompts/options and never serve as a prompt-tuning loop.
- [ ] Every scored case has an advance rubric. Correct-but-suspicious cases have
      justified reference outcomes and separately reported results.
- [ ] Durable cases, rubrics, thresholds, prompt versions and reference results
      outlive the disposable harness and support later integration regression.
- [ ] All four arms are compared, or a documented owner-approved pilot outcome
      explains why further arms are deferred without claiming their result.
- [ ] Correct candidates, genuine defects, false criticism, constraints, and
      uncertainty preservation are covered; natural/injected cases are separate.
- [ ] Raw permitted outputs, effective settings/seeds, errors and regressions,
      latency, and limitations are retained. Hidden reasoning is not collected.
- [ ] The resulting rollout decision is explicit and does not assume two or
      three passes win. No production machinery is needed to obtain it.

### Conditional production gate

A positive text-quality result qualifies only a proposed text-mode slice.
Before enabling `text_voice`, separately check the existing derivative over
revised final answers for factual/caveat preservation, valid canvas references,
and end-to-end latency. Voice output also retains its own human verification.
Pure text scores do not establish spoken quality; record these release gates
explicitly in the implementation handoff.

- [ ] Independent role requests share source evidence and preserve provenance
      while receiving the appropriate role-specific system instructions.
- [ ] Selected strategy, eligibility, settings latching, budgets, and capability
      policy are enforced by pure code; no model-produced text authorizes actions.
- [ ] Canonical history follows the approved delivery shape; internal artifacts
      and hidden reasoning cannot leak into final-answer or memory surfaces.
- [ ] Failure, cancellation, overflow, malformed output, and late results have
      tested distinct outcomes, with no silent fallback or duplicate publication.
- [ ] Final output satisfies each supported response mode; spoken derivative
      receives exact final text and remains reasoning-off.
- [ ] Existing single-pass behavior stays stable. Supported strategy x response
      mode x reasoning combinations have parameterized contract coverage; no
      unsupported pairing is silently accepted. Live quality checks use the
      selected settings matrix rather than pretending mocks prove model quality.
- [ ] A fake-backend end-to-end functional test covers the selected full turn,
      including speech derivation where applicable; edge cases use pure tests.
- [ ] `python -m pytest`, `python -m ruff check .`, and
      `python -m ruff format --check .` pass. Human-run inference, GPU, media,
      speaker/hotkey, and visual checks remain governed by `AGENTS.md`.
- [ ] Integrated behavior meets the approved quality and latency criteria, or
      rollout stops with an explicit report.

## Out of scope

Runtime cloud adapters, cloud critique/integration, and regex egress approval; automatic difficulty routing; concurrent
conversation during review; distributed/durable scheduling and automatic recovery;
multiple resident models; recursive reviewers; a universal workflow engine;
self-model reflection and memory truth repair. Future executor replacement remains
possible, but these features do not enter the implementation by implication.
