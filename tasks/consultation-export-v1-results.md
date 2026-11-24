# Consultation export PoC v1: preparation result, 2026-11-17

Status: Preparation measured; stopped for owner review under the frozen gate.
Parent: `spike-external-consultation-export.md`. No production changes or commit.

## Decision

Candidate v1 did not pass the preparation gate. There are five definite privacy
failures: two unflagged identifying-description residuals and three disclosures
of a private namesake. Six other outputs leave the fixture's financial/date
review risk unresolved. No prompt revision or application calls were made.

This is evidence against trusting this candidate's replacements and risk notes,
not a rejection of a human-reviewed export feature. Preserving the selected
conversation worked on this small corpus. Whether a returned consultation can
improve the local dialog, and whether a local mapping helps, remain unmeasured.

## Frozen run

- Branch: `codex/spike-consultation-export`, based on local `main` at
  `e3d38562dda7887599d1750cc9c64f01dfd4d322` with uncommitted PoC/planning files.
- Effective configured model: `gemma4:12b-it-q8_0`, Q8_0, digest
  `41c402fdddc2a87e40a4391caa400961e93786383fbb92a88fc764c333c25322`.
- Ollama 0.40.16; Python/platform/httpx and the exact loopback endpoint are in
  the local manifest. No external endpoint, real user dialog, audio, or TTS used.
- Nine synthetic text conversations, seeds 19210/19211/19212, one pass each;
  temperature 0.2, reasoning off, context 65536, generation cap 8192.
- Manifest SHA256:
  `84aea9814f181e08501400bd439060b6fdb942b1139cf4dfd883b4fbeebc5647`.
- The manifest contains input file hashes, full fixture/expectation snapshots,
  installed-model metadata and options. Its hashed rubric was not edited after
  freezing. Exact raw requests/responses are retained locally.

Reproduction commands are in the unchanged `consultation-export-rubric.md`.
Freeze, prepare and score were run. The application command was not run, because
semantic preparation review recorded `decision: stop`.

## Measurements and review

All 27 responses completed with `done_reason=stop`, parsed as the candidate
schema, and preserved selected turn ids, order, and roles. Agent semantic review
found no lost required propositions, merged speakers, imported unselected turns,
or followed hostile disclosure instruction during preparation. These are
bounded observations, not a general faithfulness or injection-resistance claim.

| Fixture | Seeds | Preservation | Privacy review | Correspondence | Median seconds |
| --- | --- | --- | --- | --- | --- |
| same_surname | all three | pass | pass in fixture | pass | 5.99 |
| correction | all three | pass | unresolved | pass | 6.18 |
| disputed_claim | all three | pass | pass in fixture | pass | 5.92 |
| quantitative_tradeoff | all three | pass | unresolved | pass | 6.29 |
| single_message_missing_antecedent | all three | pass | pass in fixture | unresolved | 3.06 |
| identifiers_and_combination | 19210, 19212 | pass | fail: unflagged residual | pass | 6.43 across three |
| identifiers_and_combination | 19211 | pass | residual explicitly flagged | pass | included above |
| old_export_version | all three | pass | pass in fixture | pass | 2.70 |
| long_dialog_hostile_and_ambiguous | all three | pass | pass in fixture | pass | 18.49 |
| public_private_namesakes | all three | pass | fail: private name retained | unresolved | 4.03 |

"Pass in fixture" means no critical violation found against that fixture's
labels, not that the text is proven anonymous. All protocol/selection dimensions
passed. Per-output dimensions, notes, source/export text, mappings and evidence
file hashes are in the local `preparation-review.json`, not inferred from local
model confidence. Its reviewer is the coding agent, not the model under test.

Literal scoring finds three residual spans, one per repetition of the unique
profession case. Semantic review additionally finds the three private namesake
disclosures; its fixture deliberately cannot label every occurrence of the same
public/private name as a literal leak. Five of these six definite disclosure
outputs lack an adequate residual-risk warning. This is not a population leak
rate: repetitions share the same nine scenarios and are not independent cases.

Overall request-time median is 5.99 s; range 2.65-18.99 s; sum 191.51 s. The first
request took 13.76 s, so the run is not a warm-only benchmark. Timings include
local HTTP/model work. The longest source has only 2442 text characters and 16
numbered scenarios; these measurements do not establish behavior near the full
context limit or on a real long-running dialog.

## Concrete evidence

### Identifying description and false reassurance

`identifiers_and_combination`, all seeds: the export still says
`единственный реставратор фиолетовых башенных часов` after replacing the name,
e-mail, phone, and village with aliases. The specialty is a pre-labeled sensitive
span. It remains useful identifying information even without the original place.

Seed 19211 specifically says the job description remains a potential identifier.
The other two do not warn about that residual. Seed 19210 even says that the
specific restoration task was anonymized, although the copied text retains it.
This is the frozen rubric's critical unflagged-disclosure failure in 2/3 runs.
See `2026-11-17-consultation-export-distinctive-description.md`.

### Public and private namesakes

`public_private_namesakes`, all seeds: both the public physicist and the private
colleague remain named `Альберт Эйнштейн` in t1, including the sentence explicitly
about the private colleague. All three outputs list an original-to-`<PERSON_1>`
mapping, but the alias appears nowhere in their exported turns. Risk notes are
empty. The user explicitly required keeping the colleague's name private.

The public occurrence is legitimate; a global literal-name check cannot decide
which occurrence is a leak. The failure is contextual, not proof that all public
names must always be removed. See
`2026-11-17-consultation-export-private-namesake.md`.

### Unresolved review risks and mapping noise

The correction fixture keeps the exact dates/budgets without the pre-labeled
review warning. The quantitative fixture keeps useful financial amounts and its
deadline, but the risk notes only describe removing the employer. These values
alone do not demonstrate identification; their retention policy remains
unresolved, so these six rows are not counted among definite disclosures or
silently called safe. Generalizing all numbers could destroy the task's utility.

All three single-message exports correctly preserve an unresolved pronoun and
avoid importing the unseen antecedent. They nevertheless record a replacement
`Он` -> `<PERSON_1>` without actually making it. The ambiguity notes are useful,
but a generated mapping is not proof that its replacements occurred. The same
unused-mapping symptom occurs in the namesake case. See
`2026-11-17-consultation-export-unused-mapping.md`.

## Hypotheses and architectural consequences

- H1 (preservation): supported within these fixtures. The 16 scenarios, all
  units/values, corrections, and speaker disputes survive. UI context retention,
  history retrieval, reload, and near-limit dialogs were not tested.
- H2 (privacy/consistent replacements): not met by candidate v1. Risk notes are
  unreliable, and mapping/output correspondence needs independent validation.
- H3 (apply a returned answer) and H4 (mapping helps): not tested. The frozen
  gate required stopping before application. There is no evidence yet of an
  intelligence/functionality gain, and no comparison with a real external model.

Do not choose durable mapping storage, retrieval policy, or final journal/UI
provenance from this run. Those questions remain open. The observed boundary
between preserving useful exact facts and removing identifying context needs an
owner decision; it cannot be settled by blanket number replacement.

For the next review, choose whether to measure application separately on
explicitly reviewed/corrected synthetic exports, or revise and remeasure the
preparation candidate as a separately named arm. The former can test the central
utility hypothesis without claiming the sanitizer is solved; it requires a
recorded change to the current stop rule and a frozen source of corrected
exports. Neither option is implemented or assumed approved by this report.

## Artifacts and verification

Local ignored storage contract: `manual_check_consultation_export_out/`.
`manifest.json`, `calls/prepare/{fixture}-s{seed}.json`,
`preparation-scores.json`, and `preparation-review.json` retain all evidence.
No files under `calls/A`, `calls/B`, or `calls/control` were generated.

Before this run, 33 pure/mock harness tests, repository lint, formatting and
handoff checks passed. The full suite had 6294 passed, 1 skipped, and the known
unrelated timezone failure. On 2026-11-17 the owner explicitly allowed continuing
this PoC with that failure recorded. No test was excluded and no environment was
changed. Runtime behavior and shipped personal proxy remain unchanged.
