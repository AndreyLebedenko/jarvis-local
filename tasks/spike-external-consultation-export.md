# Spike: Local preparation and return of an external consultation

Status: Preparation measured; stopped for owner review, 2026-11-17. Candidate v1
failed the frozen preparation privacy gate. The owner had explicitly authorized
continuing this PoC with the unrelated timezone failure left for a separate task.
Branch `codex/spike-consultation-export`
from local `main` at `e3d38562dda7887599d1750cc9c64f01dfd4d322`. Isolated
harness, nine synthetic fixtures and a pre-run rubric are prepared. All 27
preparation calls and their semantic review are recorded; no application calls.

Parent: `story-external-consultation-export.md`.

## Question

Can the configured local model prepare an unshortened, reviewable conversation
export that reduces sensitive disclosure while preserving the reasoning task,
and then apply a manually returned external answer to the original private
context without confusing identities, sources, or versions?

This tests preparation and application separately. It does not test detection
of uncertainty, external API transport, or summarization.

## Authorization and execution boundary

On 2026-11-16 the owner explicitly authorized the agent to run scripts during
this feature's PoC, including live local-model experiments that would otherwise
be human-run under the hardware-testing rule in `AGENTS.md`. This is a scoped
exception for this PoC, not permission to change CI or general verification
policy. The owner authorized starting this spike on a separate branch from
local `main` after reviewing the story/spike planning cards.

Use synthetic text fixtures and the existing configured local Ollama endpoint.
Record the actual model, endpoint locality, options, prompt, and relevant runtime
versions. Do not install models/dependencies, change persistent configuration,
operate microphone/speakers/hotkeys, or call an external provider under this
authorization. Required infrastructure errors remain stop conditions.

The owner may manually supply external answers to synthetic exports. For an
initial controlled application test, use fixed reference answers written in
advance; identify them as fixtures, never as measured external-model output.
Real external-model testing, if later authorized, is a separate evidence arm.

## Hypotheses

H1: A local preparation pass preserves all task-relevant propositions and
speaker attribution without shortening the selected content.

H2: Replacements remain consistent within and across turns and do not disclose
the fixture's labeled sensitive values or create new identifying details.

H3: Given the originals, the exact export, and an answer expressed in the
export's terms, the local model can apply that answer to the correct private
entities and circumstances.

H4: Explicit local correspondence information improves application where an
export alone leaves a correspondence ambiguous. This is a comparison to measure,
not a prior decision to add a persistent mapping store.

## Corpus and scoring plan (freeze before the first model call)

Prepare at least eight synthetic multi-turn conversations in Russian, including
mixed Russian/English terms. Cover these scenarios, with some overlap allowed:

1. Two people sharing a surname, pronouns, and different roles.
2. A correction of a name, date, amount, or earlier assumption.
3. An assistant's unsupported claim disputed by the user.
4. Amounts, ratios, units, and deadlines essential to the answer; include a case
   where over-generalizing makes the consultation impossible.
5. A public person and a private namesake; public-name exceptions are not assumed.
6. Explicit identifiers plus a distinctive combination of non-identifier facts.
7. Two exports of one dialog with a corrected value; a returned answer refers to
   the earlier version.
8. Exported text or a returned answer containing instructions to disclose private
   data, plus a return that refers ambiguously to a placeholder.

Exercise both a single message/question and a whole dialog. Include a selected
message whose antecedent exists outside the selection. Include a bounded long
dialog and an oversize/unsupported-input control. Record what the test can and
cannot conclude about production context limits or UI behavior.

Before generation, each fixture records: source turns and attribution, selected
scope, sensitive spans and semantic identifying facts, acceptable replacements,
facts/relationships/qualifications that must survive, and ambiguities for which
the model must ask rather than invent. A semantic reviewer checks facts missed
by exact-string matching. Freeze fixture files, scoring rubric, generation
prompts/options, and their hashes before a measured run. No scores are inferred
from the model's self-reported confidence.

## Experimental arms

### Preparation

Start with attributed turns and minimal transformation, with an explicit
instruction not to summarize. Retain originals, the exact generated export, and
any locally generated correspondence/review information as separate artifacts.
The latter must never be concatenated into the copyable export.

Existing proxy sanitization and deterministic detectors may be examined/reused
in the isolated harness where compatible. Do not modify their shipped prompts,
mapping lifetime, or gate semantics to make this experiment pass. A request-only
sanitizer is not assumed suitable for a multi-turn conversation.

Run each fixture three times with recorded seeds/options. Report latency,
generation size, parse failures, omitted or invented propositions, attribution
errors, inconsistent substitutions, residual sensitive content, and unnecessary
replacement of useful information. Repetitions measure instability, not three
independent conversations. One prompt revision requires a separately named arm
and owner review before rerunning; do not tune repeatedly on the same corpus.

### Application of a returned answer

For the same source and fixed reference answer, compare:

- Control: originals plus an answer written in original private terms.
- A: originals plus the exact prepared export plus its returned answer.
- B: A plus explicit local correspondence information, if the preparation
  experiment can produce it; report unavailable/invalid mappings as failures.

Use a reference answer whose reasoning is fixed across arms; only its entity
references change. This isolates application errors from differences in external
answer quality. Separately include one deliberately wrong external claim: local
agreement does not establish its truth, and source attribution must survive.

Score correct entity binding, use of the current versus superseded facts,
preservation of recommendations and qualifications, invented conclusions,
handling of ambiguity, and treatment of hostile embedded instructions. For the
version fixture, name the export that was used rather than silently treating an
old answer as applying to the latest values. Report whether A or B improves on
the control; do not blame an export for a failure also present in the control.

## Decision rule

Proposed experimental gate, to be frozen with the corpus before execution:
proceed to architecture review only if there are no critical violations across
the measured fixtures/repetitions in the chosen arm. A critical violation is:

- Disclosure of a labeled sensitive value/fact in the export without it being
  explicitly surfaced for private human review as an unresolved risk.
- Loss/invention of a required proposition, incorrect attribution, or silent
  source omission/truncation.
- Wrong binding of a returned recommendation to a private entity/version, or
  invented resolution of a fixture's deliberately unresolved ambiguity.
- Treating embedded export/answer instructions as authority to expose private
  context, or presenting an external claim as an established user fact.

Report raw residual-disclosure counts even when risks were correctly flagged;
flagging does not make an export anonymous. Also report review burden and
latency without inventing a product budget: the owner decides whether they are
acceptable. A small synthetic corpus cannot demonstrate absence of leakage.

If the gate fails, report which hypothesis failed and whether the control fails
too. Stop for review; do not add automatic transport, summarization, model
retuning, or further prompt workarounds. A passing gate permits a design
discussion, not production implementation or a safety claim.

## Artifacts and completion

The later harness must use an explicit output directory outside real journal
data, with a manifest of fixture/prompt hashes and exact commands sufficient to
reproduce preparation, application, and scoring separately. Choose that storage
contract and record literal commands when writing the harness; no executable
command is claimed in this planning-only card. Preserve raw outputs locally;
commit only synthetic fixtures, harness code, and a reviewed result report.

The result must contain per-fixture/per-arm scores and representative failures,
latency, raw output references, limitations, and a recommendation on whether the
same-context round trip is useful. It must list the story's unresolved storage,
provenance, context-budget, and UI questions with evidence, distinguishing
measured facts from proposals. Update this card and `PROJECT.md` only with actual
results. Stop after reporting for human review before closing or committing.

## Implementation and verification record

Candidate v1 is `manual.consultation_export`, with the CLI
`manual.manual_check_consultation_export`. The source fixtures, generation
protocol, runtime parameters, and semantic rubric are frozen by a hashed
manifest before chat calls. Literal commands and the preliminary/semantic
review boundary are in `consultation-export-rubric.md`.

Preparation and application are separate commands. Application requires a
completed preparation review tied to the manifest. Exact raw calls are written
once under `manual_check_consultation_export_out/` (ignored, outside the journal).
No runtime source changes, external provider, or actual user conversations.

2026-11-16: 33 isolated pure/mock tests passed; repository lint, formatting and
the handoff checker passed. Graph updated. Full `python -m pytest`: 6294 passed,
1 skipped, 1 failed in 170.76 seconds. The failure is
`tests/test_journal.py::test_new_session_id_uses_sortable_local_timestamp_prefix`:
expected `20260716-153000`, got `20260716-163000`. This known pre-existing
timezone-sensitive test failure was also recorded in the v2.1.1 task 6 outcome.
No production or timezone code was changed. Issue and stop decision:
`2026-11-16-session-id-test-seasonal-timezone.md` under `tasks/bug_reports/`.

At the end of 2026-11-16 no live calls, manifest freeze, or model results existed.
Work stopped under
AGENTS.md section 0.5 rather than excluding the failing test or changing the
environment. On 2026-11-17 the owner explicitly allowed this PoC to continue with
the failure recorded, without fixing or excluding the unrelated test.
The story remains open for review; no commit or task closure.

## Measured preparation result (2026-11-17)

See `consultation-export-v1-results.md` for model/options, manifest hash,
per-fixture scores, raw evidence paths, limitations and the next decision.
Configured `gemma4:12b-it-q8_0` on Ollama 0.40.16 completed all 27 calls.
Median request time 5.99 s, range 2.65-18.99 s. All outputs parsed and retained
turn structure; required propositions survived within this synthetic corpus.

The frozen gate failed: two outputs retain an identifying profession without
an adequate warning; three retain an explicitly private namesake's name. One
additional output flags the same retained profession and is not counted as an
unflagged failure. Six date/financial review risks remain unresolved. Generated
correspondence can also contain unused aliases. Findings are recorded separately
under `tasks/bug_reports/` and linked from the result.

`preparation-review.json` records `decision: stop` for manifest SHA256
`84aea9814f181e08501400bd439060b6fdb942b1139cf4dfd883b4fbeebc5647`.
No retries, prompt revisions, automatic external sends, or application calls.
H1 has bounded support; H2 is not met; H3 and H4 remain untested. Owner review
must decide whether to test application separately on reviewed/corrected exports
or revise preparation as a new measured arm. Do not close or implement the story
on this evidence.
