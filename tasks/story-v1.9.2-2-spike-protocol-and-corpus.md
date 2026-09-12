# Task v1.9.2-2: Spike protocol and corpus preparation

**Status:** Deferred 2026-09-12. Retained as the draft of stage 1 (repair
measurement) under the accepted reduction proposal
(`spike-1.9.2-reduction-proposal.md`); the authored corpus, rubrics, protocol
sidecar and egress manifest described here belong to stage 1 and are not
prepared while stage 0 (card v1.9.2-9) is the active slice. Do not start this
card until stage 0's outcome authorizes stage 1.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Spike card (contract source):** `task-v1.9.2-1-local-answer-revision-spike.md`, Phase 0.
**Created:** 2026-09-12.
**Current boundary:** Offline preparation only. No live Ollama call, no cloud
call, no runtime change. Live execution is blocked on gates G0/G1 and owned by
later cards.

## Summary

Materialize the spike card's Phase 0 contracts as actual files: the fixed
corpus with rubrics, the frozen protocol with prompts and effective options,
the machine-readable protocol sidecar, and the cloud egress manifest. All
numeric values come from the spike card as proposals awaiting G0 approval;
this card adds no new thresholds.

## Deliverables

1. `tests/answer_revision_benchmark/` package of passive fixtures:
   - case manifest with stable IDs, category, split, provenance;
   - 6 development cases (one per category);
   - 18 held-out cases (3 per category);
   - 6 injected-defect candidate definitions (development only);
   - 20 checker-calibration answer sheets (10 defective, 10 correct, including
     5 suspicious-correct) with human-verifiable expected labels;
   - per-case rubrics: 3-6 binary/ternary items each, severity fixed per the
     spike card's minor/material/critical definitions.
2. `tasks/v1.9.2-spike-protocol.md`: frozen role prompt texts (Revision A
   first-person, Revision B neutral, Critic, Integrator, GLM checker),
   complete effective options, seeds, timeouts, caps, run matrix, call
   ceilings, approval record placeholders, artifact locations, and the Ollama
   privacy-policy reference dated 2026-09-12.
3. A machine-readable protocol sidecar (JSON) carrying the exact frozen
   values and hashes; Markdown is the readable record, never heuristically
   parsed configuration.
4. `tasks/v1.9.2-spike-cloud-manifest.json`: explicit cloud-eligible
   nonpersonal case/packet allowlist.
5. `.gitignore` rule `manual_check_answer_revision_out/` added and verified
   before any payload-writing code exists (no leading slash, matching the
   file's existing raw-output convention).

## Content rules

- Case and rubric content (requests, evidence E, reference answers, checkable
  justifications) is written in Russian, matching the dialog language of the
  runtime. Service documents, identifiers, and code stay in English. Rubrics
  are written before any arm output exists.
- Every case carries: ID, source class, split, original request, evidence E,
  constraints, allowed answer alternatives, expected properties, forbidden
  errors, severity, checkable justification.
- Near-duplicates and variants of one problem stay in the same split. Cases
  requiring external fact lookup are excluded from the scored set. Cloud-
  eligible content needs explicit manifest approval; authorship is not egress
  permission.
- If a natural draft is wrong it is not labeled known-correct because of its
  category; calibration sheets supply guaranteed correct-answer traps
  independently.
- The protocol carries a pre-registered expectation for baseline B: on this
  model, `high` reasoning matched `off` on faithfulness traps in the recorded
  v1.8.0-22 experiment, and most held-out categories are faithfulness traps,
  so B is expected to land at A's quality level. If confirmed, the report
  states this as a second independent confirmation on a new task class; if
  refuted, that is a stronger result for the baseline. B's degeneracy is a
  possible finding, not a quietly cleared hurdle.
- The protocol fixes how the report must phrase the win criteria: observed
  stable-win rate with its denominator, and an explicit statement that the
  "at least 3 stable case wins" threshold is a floor, not an effect size
  (five of six held-out categories carry a defect by construction).

## Open questions fixed for G0 decision (owner)

These are raised by the review notes (`spike-1.9.2-tasks-notes.md` findings
19 and 23; `spike-1.9.2-tasks-notes-2.md` findings 30 and 33); the protocol
drafts the owner's chosen answers, G0 approves them:

1. **G2 introduced-defect denominator.** Whether the zero-introduced-
   material/critical-defects test runs over all 18 held-out cases or over
   15 excluding correct-but-suspicious, with a narrowed "qualifies except
   for correct-but-suspicious inputs" outcome in the latter case. Stress-
   category results are computed and reported separately under either choice.
2. **Framing evidence budget.** Whether to add development cases
   specifically for the first-person/neutral framing comparison - +14 local
   calls for 2 cases or +21 for 3, either of which requires an explicit
   amendment of the 260-call ceiling, which currently forbids exploratory
   variants - or to keep 6 cases and record the framing as "selected by
   tiebreak, not tested" in the report.
3. **G2 latency-ratio anchor.** The proposed table divides by baseline B's
   median; B is expected to be roughly 5x A in cost with no quality gain
   (pre-registered expectation), so the ratio rows would pass automatically
   and bind nothing. Proposed amendment: anchor full-latency ratios to A's
   median (e.g. R_full <= 3.0 x A median, I_full <= 4.0 x A median, keeping
   the existing I <= 1.8 x R incremental row and the absolute p90 caps of
   60 s / 90 s), keep the B ratios as reported documentation columns, and
   make the absolute p90 caps the operative cost gate. Numbers are proposals;
   the owner sets them at G0.

## Boundary

- No harness code, no CLI entry point, no scoring logic (task v1.9.2-3).
- No live local or cloud model inspection by the agent.
- No revision of settled audio facts, no media handling.
- Any conflict found between this card's contracts and the spike card stops
  work under AGENTS.md 0.2.

## Verification

- Pure tests or a validation routine assert manifest structure: counts per
  split/category, rubric item counts within 3-6, severity presence, calibration
  sheet label counts (>= 10 material/critical positives, >= 10 corresponding
  negatives), held-out/development disjointness.
- Egress manifest review: every cloud-eligible packet contains no personal
  content; Journal cases absent.
- `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`
  green.
- `tools/graphify.ps1 update` after source/fixture changes, per AGENTS.md.

## Acceptance criteria

- [ ] All Phase 0 files exist with the spike card's stated contracts.
- [ ] Rubrics predate outputs; no held-out case text appears in any prompt
      selection material.
- [ ] Ignore rule for raw output directory is committed and verified.
- [ ] Protocol sidecar hashes match the Markdown protocol content.
- [ ] Green pytest/ruff gates; no live inference anywhere.
- [ ] Stop for owner G0 review before any harness execution card proceeds.