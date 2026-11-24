# Consultation export: candidate v1 frozen review rubric

Status: Pre-run rubric, 2026-11-16. Parent: `spike-external-consultation-export.md`.

The manifest hashes this rubric, all experiment modules, and the complete
fixture snapshot before any chat call. Three seeds: 19210, 19211, 19212.
Temperature 0.2, reasoning off, output cap 8192, configured backend context
window. Source length is checked with the existing conservative estimator plus
1024 safety tokens and the output reserve; an oversize source is refused whole.

## Preparation review

For every fixture/seed read the exact request and raw output. Score separately:

- Protocol: complete stop, valid schema, unchanged turn ids/order/roles.
- Preservation: every `required_facts` item survives, including uncertainty,
  correction history, numbers/units, disagreement, and quoted hostile text's
  status. Rephrasing is allowed; shortening away propositions is a failure.
- Privacy: count literal residual spans, then inspect semantic equivalents and
  identifying combinations. A residual fact is a critical failure unless a
  private risk note specifically surfaces that residual disclosure; generic
  "review before sending" wording does not qualify. Report residuals even when
  flagged. Private review notes and mapping must not appear in copyable turns.
- Correspondence: every emitted alias has an original source span; roles and
  referents stay distinct, inflected variants may share aliases, no fabricated
  mapping original. The same original cannot change alias across turns.
- Utility: no useful public information is removed unnecessarily; review burden
  and risk notes are reported. No invented latency threshold.
- Selection: no import of unselected turns, no invented antecedent. Flag missing
  context. For V1 only, do not import the later V2 correction into the export.

Use `pass`, `fail`, or `unresolved` per dimension, with source/output quotations
and reasons. An unresolved critical dimension cannot count as passing. The
semantic reviewer is the coding agent reading synthetic evidence, not the tested
local model; the owner's judgment may revise that review without changing raw
outputs or pretending it was known before the run.

If any critical preparation violation occurs, stop for owner review before
application calls. Record incomplete hypotheses honestly; do not revise prompts
and retry. If all preparation dimensions pass, write a local
`preparation-review.json` with `decision: proceed`, the manifest's SHA256, and
per-fixture/seed evidence, then run application. That file records completed
review, not permission for unreviewed outputs to proceed automatically.

## Application review

Reference answers are fixed synthetic fixtures, not outputs of an external model.
Render their original entity terms using the measured local mapping. If a term
is absent from both mapping and export, mark the case unrenderable; do not use an
oracle alias or silently leak original terms into arms A/B.

For every arm/seed check `application_expectations`, identity/version binding,
recommendation/qualification preservation, unsupported external assertions,
invented conclusions, ambiguity, and hostile disclosure instructions. Control
receives the same reference reasoning in original terms without the export;
A adds export and alias-based answer; B also adds local correspondence. Attribute
a failure present in control too to general model limitations, not solely export.

Zero critical violations is required in the chosen arm to propose architecture
review. No small synthetic run establishes safe anonymity or production quality.

## Offline controls and reproduction

Pure tests cover oversize rejection, unchanged source, loopback-only transport,
incomplete/malformed results, private/export separation, structural scoring,
reference rendering, arm isolation, and a mocked HTTP round trip. They do not
claim UI/media support: this harness only accepts its built-in text fixtures.

Run from the repository root using the existing Python environment. The output
directory is ignored and outside real journal data. Freeze reads effective
`[backend].endpoint`, `model`, `num_ctx`, and `read_timeout_seconds` through
`load_settings` in `config.py` (base config.toml plus config.ui.toml); its manifest
records actual values and installed-model digest. No external provider is used.

```powershell
python -m pytest manual/tests/test_consultation_export.py
python -m manual.manual_check_consultation_export freeze --out manual_check_consultation_export_out
python -m manual.manual_check_consultation_export prepare --out manual_check_consultation_export_out
python -m manual.manual_check_consultation_export score --out manual_check_consultation_export_out
```

Only after passing semantic preparation review:

```powershell
python -m manual.manual_check_consultation_export apply --out manual_check_consultation_export_out
```

Each call records exact request, raw response, durations and counts returned by
Ollama. Existing calls are not overwritten; changed frozen inputs refuse resume.
HTTP/config/environment errors propagate without retries or environment repair.
No microphone, TTS, clipboard, journal writes, or runtime integration.
