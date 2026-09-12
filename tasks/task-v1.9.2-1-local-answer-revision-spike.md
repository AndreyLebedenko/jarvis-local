# Task v1.9.2-1: Local answer revision evaluation spike

**Status:** Planned. Preparation authorized by the accepted story; live execution
is blocked on gates G0 and G1. Numeric values below are proposals for G0, not
already approved merely because this planning card is committed.
**Staged reduction, accepted 2026-09-12:** the single large experiment
described below is deferred in favor of the staged shape in
`spike-1.9.2-reduction-proposal.md`. Stage 0 (card v1.9.2-9) is the only
authorized step now. This card remains the contract source and draft for
stage 1 (repair measurement); its gates G0/G1/G2 apply to stage 1 if and when
stage 0's stop rule authorizes it, not to stage 0.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Created:** 2026-09-12.
**Lifecycle:** This card is the contract source for cards v1.9.2-2 through -8
and stays in `tasks/` with the story; it moves to `tasks/done/` only when card
v1.9.2-8 closes, never independently.
**Revision 2026-09-12 (review-notes-2 absorption; uncommitted corrections
pending owner review):** phase 2 step order corrected - GLM calibration and
development/injected sheet scoring precede the framing-dependent calls
(finding 26); GLM named as the development/injected sheet scorer with human
adjudication (finding 25); the pilot CLI is split with an explicit
framing-selection seam (finding 27); the high-reasoning revision condition is
re-anchored to an evaluable pilot latency bound (finding 31); G1/G2
underpowered-corpus reporting and conditional repair rate added (finding 29);
the raw-output ignore rule follows the `.gitignore` convention without a
leading slash (smaller note). The G2 latency-ratio anchor is a G0 decision
drafted in card 2 (finding 30); G2's introduced-defect denominator remains a
G0 decision (finding 19).
**Current boundary:** Prepare a reproducible developer-only comparison, obtain
protocol approval, hand over live commands, analyze returned evidence, and stop
for the owner's decision. No production feature implementation in this card.

## Question and deliverables

Does independent local revision improve final text on the declared task set at
an acceptable cost compared with both ordinary and stronger single-pass answers?
Does a separate critic add useful value beyond two passes?

Deliver a fixed corpus/rubrics, a pure-tested manual harness, a frozen protocol,
raw permitted run artifacts, item-level scores and human corrections, and a report
with one of three outcomes per strategy: qualifies for a bounded text slice;
does not meet the gate in this scope; inconclusive/deferred. No universal accuracy
claim and no automatic production rollout.

Read before preparation: `PROJECT.md`, the story and notes, `AGENTS.md`,
`manual_check_graded_reasoning.py`, `tests/retrieval_benchmark/corpus.py`,
`pyproject.toml`, `.gitignore`, and the backend/config payload precedents. Query
the existing graph before broad source exploration. No live model inspection by
the agent. Do not revise settled audio facts or build media handling for this task.

## Roles and authority

| Role | Owns | Does not own |
| --- | --- | --- |
| Implementing agent | Cases, rubrics, harness, pure tests, manifest, report preparation | Live Ollama/GPU execution, threshold approval, final release choice |
| Owner/operator | Approves protocol and egress cases, starts batches, scores/audits, adjudicates, accepts result | Repetitive manual dispatch of individual requests |
| Local generator | Candidate D from original E under ordinary generation contract | Critique or tool execution |
| Local reviser | F from E and labeled D, one chance to retain or repair | Inventing prior conversation or new evidence |
| Local critic | C with grounded findings or no findings | Actions, rewriting the source, final-answer publication |
| Local integrator | F from E/D/C, rejecting unsupported objections | Treating critique as verified fact |
| Pure checker | Exact fixture properties and independently computed arithmetic | Guessing semantic correctness from keywords |
| Cloud GLM checker | Preliminary rubric-item extraction with evidence | Preference ranking, setting thresholds, deciding its own reliability |

All local roles use one configured local model sequentially. No spawned agents,
parallel model residency, cloud critic, external tools, or runtime modifications.

## Phase 0: prepare the protocol and corpus (agent, offline)

Prepare the actual files below. This card specifies their contracts, not that
they already exist. Use UTF-8 explicitly in Windows file operations.

- `tests/answer_revision_benchmark/`: manifest, development/held-out cases,
  checkable reference material, rubrics, scoring logic and pure tests as appropriate.
- `manual/manual_check_answer_revision.py`: human-run entry point.
- `manual/answer_revision_cloud_checker.py`: isolated cloud transport if a separate
  module is needed; never imported directly or transitively by `src/jarvis`.
- `tasks/v1.9.2-spike-protocol.md`: frozen protocol, role prompt text, complete
  effective options, approval record, run matrix and hashes.
- `tasks/v1.9.2-spike-report.md`: sanitized outcome tables and decision record.
- `manual_check_answer_revision_out/<run-id>/`: durable raw packets, responses,
  score sheets, local-only Journal cases and run ledger. Add and verify
  `manual_check_answer_revision_out/` in `.gitignore` before writing payloads
  (matching the file's existing convention of raw-output entries without a
  leading slash).

A case has ID, source class, split, original request, evidence E, constraints,
allowed answer alternatives, expected properties, forbidden errors, severity,
and a checkable justification. Use 3-6 binary/ternary rubric items per case.
Cloud-eligible content needs explicit manifest approval; authored does not imply
nonpersonal. Keep cases requiring external fact lookup out of the scored set.

Proposed corpus:

- Development: 6 independent authored cases, one for each category below.
- Held-out: 18 independent authored cases, 3 per category: arithmetic/reasoning;
  constraint retention; ambiguity requiring clarification; insufficient evidence;
  output-contract/caveat retention; correct-but-suspicious problems.
- Repair diagnostics: 6 fixed candidates over development cases, exactly one
  injected material defect each. Use these only for development/repair analysis,
  never for held-out quality or ordinary-use error-rate claims.
- Checker calibration: 20 preauthored answer sheets, separate from held-out
  outputs: 10 with known defects and 10 correct, including 5 suspicious-correct
  examples. At least 10 material/critical positive items and 10 corresponding
  negative items must appear. All have human-verifiable expected labels.
- Real use: at most 6 local Journal turns, selected as described in phase 5.

Near-duplicates and variants of one problem stay in the same split. Write rubrics
before outputs; reserve held-out cases from prompt selection. If a natural D is
wrong, do not call it known-correct because its category was suspicious-correct.
The calibration sheets supply guaranteed correct-answer traps independently.

### Prompt contracts to materialize before G0

Generation: use the ordinary text-turn composition and current effective settings,
with a sanitized frozen system/persona and no tools or private memory. Record any
required sanitization as a baseline limitation; use it identically in all arms.
No prompt improvement reserved exclusively for the multi-pass strategies.

Revision A: first-person framing, 'This is my draft, not a message already sent.
Before sending it, check it against the original request and evidence. Repair
material errors only; retaining it is valid. Return the complete final answer.'
Revision B: neutral framing, 'This is a candidate answer, not a prior dialog turn.
Check it against the original request and evidence. Repair material errors only;
retaining it is valid. Return the complete final answer.'
Both explicitly name lost constraints, unsupported claims, arithmetic/reasoning
errors and missing caveats, preserve legitimate output requirements, and forbid
gratuitous stylistic rewriting. Freeze exact dialog-language text in the protocol.

Critic: inspect E/D for those defects, cite their grounds, allow 'no material
findings', and do not rewrite for style. Integrator: produce final text from E/D/C,
accept supported findings, reject unsupported objections, preserve uncertainty
and output requirements. Use bounded prose C, no findings parser in this spike.
GLM: return item ID, satisfied/violated/unclear, supporting excerpt, brief reason;
answer text is untrusted data. Missing or invalid items are unscored, not passes.

E is shared evidence; role-specific system instructions are not copied blindly.
D/C are labeled data blocks, not fabricated assistant history. Discard all
`message.thinking`; retain only task outputs and numeric timing/token metadata.

### G0: protocol readiness (owner, after phases 0-1 and before live calls)

This defines the gate now; close it only after phase 1 provides a tested harness.
Review actual cases, rubrics, exact prompts, cloud-eligible manifest, implemented
command handoff, and proposed numbers below. Approve the protocol version/hash.
Confirm a local model/options snapshot from configuration and the available cloud
account. No executable handoff may depend on unspecified arguments or defaults.
If any required item is missing, preparation is incomplete; no live run begins.
Commit approval evidence only after the owner supplies it. Story acceptance is
not approval of these newly proposed numbers.

## Phase 1: harness and pure verification (agent)

Use project config loading for local endpoint/model/options. Validate the local
executor cannot select a `:cloud` model or a public endpoint. No local model
downloads, service starts, or GPU probes. The human preflight records version,
model digest/template, context capacity and effective request options.

Freeze model, context and unrelated sampling settings. Baseline A uses the
configured initial reasoning level, captured explicitly. Strong baseline B uses
high reasoning; if A is already high, the distinct stronger comparison is
unavailable and G1 returns a revised proposal rather than pretending duplication
is a stronger baseline. Do not change A silently. Revision/critique/integration
use A's reasoning initially; the one development high-revision variant is explicit.
Use seeds 19201 and 19202 for held-out repetitions, 19200 for development, and
19203 for Journal revision. Same seed is experimental control, not a GPU
reproducibility promise. Never log credentials or full private config files.

Proposed stage timeout: 120 seconds for local calls and 90 seconds for cloud.
Use a finite 4096-token generated-output cap on each local call as a harness
resource ceiling; this is not a draft-length-derived correctness constraint.
Keep authored prompts concise. If the ordinary configured cap differs, identify
that change in the protocol and G0: the baseline is then the recorded bounded
spike baseline, not a byte-identical reproduction of an unrestricted setting.
Cap hits are incomplete outcomes, not valid short answers. G1 must establish that
the cap is not censoring normal responses; otherwise revise protocol before
held-out runs. Preflight full per-pass budgets and recheck actual D/C lengths.

Persist run/case/arm/repeat/stage IDs, hashes, options, timestamps, terminal status,
and exact permitted packets/results. Terminal results are immutable. Resume skips
completed IDs and never silently retries an uncertain request. Interrupt stops
future dispatches; no fallback publication or new turn. Infrastructure failures
obey `AGENTS.md`: report and stop, without changing shell/model/provider.

Pure tests cover composition/isolation, budgets/caps, deterministic matrix counts,
seed assignment, cloud allowlist rejection of Journal cases, scorer parsing,
severity/scoring, interruption/resume, no duplicate dispatch/publication, secret
redaction and no runtime import of the cloud helper. One fake-client end-to-end
functional test exercises all selected arms and the report path. Run project
pytest/Ruff gates. No test invokes local or cloud inference.

### Required CLI contract (to implement, not executable yet)

All commands run from repository root. Before G0 the actual handoff must verify
these flags with the implemented parser and cite their source; adjust this card
if the implementation needs a different approved contract.

```powershell
python -m manual.manual_check_answer_revision validate --protocol tasks/v1.9.2-spike-protocol.md
python -m manual.manual_check_answer_revision run --phase pilot-framing --run-id v192-pilot-01
python -m manual.manual_check_answer_revision score-cloud --run-id v192-pilot-01 --approve-manifest tasks/v1.9.2-spike-cloud-manifest.json
python -m manual.manual_check_answer_revision select-framing --run-id v192-pilot-01
python -m manual.manual_check_answer_revision run --phase pilot-continuation --run-id v192-pilot-01
python -m manual.manual_check_answer_revision score-cloud --run-id v192-pilot-01 --approve-manifest tasks/v1.9.2-spike-cloud-manifest.json
python -m manual.manual_check_answer_revision freeze --run-id v192-pilot-01
python -m manual.manual_check_answer_revision run --phase held-out --run-id v192-heldout-01
python -m manual.manual_check_answer_revision score-cloud --run-id v192-heldout-01 --approve-manifest tasks/v1.9.2-spike-cloud-manifest.json
python -m manual.manual_check_answer_revision run --phase journal --run-id v192-journal-01
python -m manual.manual_check_answer_revision report --protocol tasks/v1.9.2-spike-protocol.md
```

`pilot-framing` covers the framing-comparison batch (A, B, revision A,
revision B per case); `pilot-continuation` covers high-reasoning revision, C,
I, and the injected diagnostics after the framing is selected. `select-framing`
applies the frozen selection rule to the scored sheets, records the choice and
its provenance (measured or tiebreak) into the run ledger and the protocol
sidecar, and refuses to run while decisive sheets are unscored or disputed.
The held-out `run` reads the selected framing from the sidecar and fails
validation if it is absent. `select-framing` is offline. Adjust this card if
the implemented parser needs a different approved contract.

Validation, freeze and report are offline. All `run` and `score-cloud` commands
are human-run. Use explicit `--resume` only after reviewing an interrupted ledger;
no automatic retry. A machine-readable protocol sidecar must carry exact frozen
values and hashes; Markdown is the readable approval record, not heuristically
parsed configuration. Generate the sidecar and egress manifest during preparation.
Authentication uses the documented provider credential mechanism, named literally
in the final handoff after checking the official API docs; never embed its value
in arguments, protocol, source, or logs. No live command is authorized by this card
until the stated gates have passed.

## Phase 2: checker calibration, development pilot, and diagnostics (human-run)

Revision 2026-09-12: calibration and sheet scoring moved ahead of the
framing-dependent calls, so the checker is validated before its scores are
relied on. GLM scores the development and injected final sheets; the human
adjudicates disputes. Phase 2 consumption: 62 local calls (2 preflight + 42
development + 18 injected) and 69 cloud calls (1 connectivity probe + 20
calibration + 36 development sheets + 12 injected sheets).

Order of execution:

1. Preflight probes (2 local calls): record model version/digest/template,
   context capacity, effective request options, baseline A's reasoning level.
2. GLM calibration (20 cloud calls over preauthored sheets) and the synthetic
   connectivity probe (1 cloud call). Calibration needs no development output;
   a failed calibration stops before the local budget is spent, for a revised
   proposal or an owner-approved human-scoring fallback - uncalibrated GLM
   scores are never relied on.
3. Framing comparison batch: per case - A generation, B high baseline,
   revision A, revision B (4 local calls x 6 = 24). Generate D once and reuse
   it. The selected R framing is recorded through the CLI's explicit
   selection step (see the CLI contract), which applies the frozen rule to
   GLM-scored sheets: fewer introduced material errors, then more corrected
   defects; ties keep first-person A. The choice is recorded as exploratory,
   not confirmation evidence.
4. Pilot continuation: high-reasoning revision using the better framing, C and
   I (3 local calls x 6 = 18). Choose high revision only if it corrects at
   least one additional development material error, adds none, and satisfies
   the pilot latency bound below. No further prompt tuning in this protocol
   version.
5. Injected diagnostics: 6 fixed candidates through selected R and C/I
   (3 calls x 6 = 18 local calls). Do not count their fabricated initial
   generation as a live call or as a naturally occurring defect. Keep their
   scores out of the held-out gate.
6. GLM scores all 36 development and 12 injected final sheets; human
   adjudication overrides GLM on disputes. Record per-stage timings and
   scoring minutes/sheet; derive whether the full matrix fits the agreed
   owner-time and machine-time budgets.

Pilot latency bound (replaces the unevaluable held-out ratio reference):
choose high revision only if its full user latency (A + R_high) on
development cases is at most 2.5 x the development B median and at most
60 seconds absolute.

Underpowered-corpus check (G1 input): report the count of development cases
whose natural A draft violated at least one material rubric item. If fewer
than 3 development drafts contain a material defect, flag the corpus as
underpowered for the win threshold before any held-out calls are spent.

Calibration acceptance rules: zero missed material/critical defects, at most
1 false defect sheet out of 10 correct sheets, at least 90% determinate item
agreement, and at most 2 unclear sheets out of 20. These are operational
acceptance rules on this sample, not proof of a small population error rate.
Human adjudication overrides GLM.

### G1: feasibility and freeze (owner)

Confirm real timings, scoring effort, cap completion, checker calibration, exact
local/cloud model metadata, selected revision framing/reasoning, and remaining
budget. Allow held-out execution only if all comparisons fit the agreed limits.
At most 2/42 development calls may be incomplete; any such outcome must be
explained before proceeding. Systematic cap censoring or scoring unreliability
requires a revised protocol, not trimming the failed outputs. If GLM fails,
reduce to a human-scoreable proposal or stop inconclusive. No automatic fallback.
Freeze all prompts/options, rubric versions and thresholds before held-out output.
Also confirm the underpowered-corpus flag: if fewer than 3 development drafts
contained a material defect, held-out execution is deferred until the owner
approves proceeding anyway or amends the corpus.

## Phase 3: held-out paired experiment (human-run)

18 cases x 2 seeds x 5 calls: A generation, B high baseline, selected R, C, I
= 180 local calls. Four final-answer sheets per case/repeat (A, B, R, I) = 144.
GLM scores each sheet independently without arm labels; pure checks run first.
Score all four answers of a case close together. Shared A reduces experiment
runtime; report full user costs R=A+R and I=A+C+I, including prefill and reasoning.
Do not equate a reasoning label with matched compute. Report actual B/R/I latency;
use the bands below, and state when B is not a close cost match.

Report each category separately, especially suspicious-correct and uncertainty
cases. Pairwise direction is based on the predefined material items: win fixes at
least one material defect without adding one; loss introduces a material defect;
otherwise tie (minor edits reported separately). A case counts as a stable win
only if both repetitions win or one wins and the other ties; any repetition loss
counts as a loss for that case. Mixed win/loss is never netted into a stable win.

## Phase 4: human audit, drift check, and numeric gate

Human reviews every alleged material/critical introduced error, every unclear or
conflicting decisive assessment, every case contributing to a claimed stable win,
and a random 10 passing held-out sheets (seed 19204), including suspicious-correct
cases. Deduplicate obligations before estimating effort. Stop for a smaller scope
or inconclusive result if audit demand exceeds its budget; do not skip audits.
Repeat the 20 calibration sheets through GLM at the end. Same acceptance rules
apply; any new missed decisive defect or changed decisive calibration verdict
requires adjudication before trusting the gate. Freeze/report cloud metadata and
alias limitations; do not silently rescore until agreement improves.

### G2: provisional qualification criteria (proposed for G0)

Evaluate complete held-out case pairs only. Require all 18 cases x 2 repeats for
an affirmative outcome in this protocol version; missing cases give inconclusive,
with failure rates reported. No replacement after seeing held-out performance.

| Test | Two-pass R | Three-pass I |
| --- | --- | --- |
| Improvement over A | At least 3 stable case wins | At least 3 stable case wins |
| Improvement over B | At least 2 stable case wins | At least 2 stable case wins |
| Increment over R | Not applicable | At least 2 stable case wins |
| Introduced material/critical defects versus A or B | Zero | Zero; also zero versus R |
| New minor-only defects | At most 1/18 cases | At most 1/18 cases |
| Median full latency / B median | At most 2.5 | At most 3.5 |
| Incremental median latency | Not applicable | At most 1.8 x R median |
| Whole-strategy p90 latency | At most 60 seconds | At most 90 seconds |

Severity is fixed per rubric: minor = presentation nuisance without changing a
required result; material = wrong result, lost constraint or consequential caveat;
critical = an error the case rubric explicitly identifies as unacceptable for its
hypothetical consequence. No medical/legal/high-impact user decisions are executed.
Critical vetoes are never averaged away. A strategy meeting counts on these small
sets qualifies only for a bounded text implementation proposal, not default-on use.

Reachability and conditional repair reporting (G2 inputs): count held-out
A drafts (case x repeat) that violated at least one material rubric item. If
fewer than 3 such drafts exist, the win threshold was unreachable and the
outcome is recorded as inconclusive/underpowered, never as nonqualification -
a ceiling is a property of the corpus, not evidence against the mechanism.
Report the conditional repair rate: defects repaired by each strategy divided
by the number of defective A drafts, alongside the whole-answer end-to-end
quality figures. The latency-ratio rows above are anchored to baseline B's
median, which is expected to be degenerate (pre-registered expectation);
their operative reading and possible re-anchoring to A are the G0 decision
drafted in card 2 - until then the absolute p90 caps are the operative cost
gate and the B ratios are reported as documentation columns.

## Phase 5: small local real-usage check (human)

Select up to 6 text-only completed Journal turns from the 14 days preceding the
protocol freeze, sorted by timestamp. Exclude media, executed tools, missing source
evidence, and source packets that cannot be reconstructed faithfully. Use evenly
spaced indices floor((i+0.5)*N/6) for N>=6; otherwise all eligible turns. Record N,
exclusions and selected references locally. Do not cherry-pick replacements based
on answers. No available sample means ordinary-use evidence is unavailable.

Reuse each published answer as D; selected R and C/I cost 3 calls/turn = at most 18.
Score locally, at most 12 human comparisons. Never send Journal data to GLM.
Label this retrospective replay, not a fresh end-to-end baseline comparison.
Unavailable ground truth allows not-assessable. This small sample can expose a
practical regression, but cannot estimate a general user error rate precisely.
An adjudicated material regression pauses rollout for owner review even if G2
passed. Fewer than 4 assessable turns leaves ordinary-use applicability unmeasured;
it does not invalidate the separate authored-case result.

## Resource envelope (proposed, approval required)

Owner budget first: 30 minutes setup/launch/approvals and 120 minutes evaluation
work: calibration 30, pilot choice 12, random audit 15, Journal comparisons 18,
winning/defect/dispute adjudication 30, final decision 15. These are caps, not
claims about actual scoring speed. The pilot estimates minutes/sheet and derives
whether the matrix fits; owner approves reductions before held-out runs.

Local machine ceiling: 4 hours across phases. Local call ceiling: 260, comprising
2 preflight probes + 42 development + 18 injected diagnostics + 180 held-out +
18 Journal. Do not add retries or exploratory variants to this count.
Cloud ceiling: 233 calls = 1 synthetic connectivity probe + 20 calibration +
36 development final sheets + 12 injected final sheets + 144 held-out sheets +
20 end calibration. Cloud machine-time ceiling: 60 minutes. Calls are sequential;
no pairwise preference calls. At most one checklist request per answer sheet.

Financial proposal: no purchase/top-up/overage; existing prepaid/subscription
allowance only. At G0 verify the account's actual billing mode; if requests could
incur uncapped new charges, cloud execution is blocked pending an explicit numeric
spend cap. Stop on account quota exhaustion; do not change provider or buy capacity.
No per-token price is assumed from a model name. Track reported token usage and
actual charges when available, with missing accounting metadata stated explicitly.

## Cloud endpoint and retention boundary

Verified official model tag on 2026-09-12: `glm-5.3-flash:cloud`, documented at
[Ollama model page](https://ollama.com/library/glm-5.3-flash).
Use Ollama Cloud only through its documented API/auth path; verify access and
version metadata in human-run preflight, not by substituting a similar model.
[Ollama privacy policy](https://ollama.com/privacy) states transient content
processing, no retention beyond request fulfillment and no training on it;
service metadata is separate. Record date/reference. ZDR does not make egress
local. The checker is spike-only and receives only manifest-approved nonpersonal
packets. No Journal exporter is connected to the cloud path, even when anonymized
text appears plausible. Cloud errors/unclear verdicts cannot become passing scores.

## G3: final report and owner decision

Report all arms and exclusions, raw artifact hashes/locations, score denominators,
case/repeat outcomes, corrected and introduced errors, checker calibration/audits,
cloud drift/version limits, actual cost/latency and consumed human time. Do not
count repetitions as independent problems. Do not tune on held-out results.
A new experiment needs fresh held-out cases; old cases remain useful regressions.

Choose a bounded text-slice proposal, nonqualification in tested scope, or
inconclusive/deferred with one specific next question. Text success does not
license `text_voice`: later implementation must check the reasoning-off derivative
for factual/caveat fidelity, valid canvas references and full latency over revised
answers, plus human voice/visual checks. No broker, settings UI or production
three-pass work starts as part of this card. Stop for human review before closing
this task; recording a report is not automatic feature approval.

## Acceptance checklist

- [ ] G0 is recorded against actual files and concrete proposed numbers; no live
      execution occurred before approval.
- [ ] Harness, fixtures, manifests and report logic have pure tests and green
      `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`.
- [ ] Exact executable human handoff cites implemented commands, credential name,
      endpoint/default sources, ignore rule and every state-independent setup step.
- [ ] G1 records calibration, feasibility and frozen framing/options before held-out.
- [ ] G2 is computed from complete, audited held-out evidence or marked inconclusive.
- [ ] Journal sample is local-only, reproducibly selected and separately interpreted.
- [ ] G3 records the bounded decision, durable artifacts and outstanding limitations.
- [ ] No runtime imports/changes, real-data egress, hidden-reasoning retention,
      unapproved cost, silent retry, or production rollout was introduced.

All `AGENTS.md` stop conditions apply. Unexpected infrastructure errors stop the
run; scientific nonqualification is a valid result, not a reason for workarounds.
