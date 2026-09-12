# Task v1.9.2-9: Stage 0 damage and inertness probe

**Status:** Planned, not started; deliberately held back by the owner
(2026-09-12) until more data accumulates - the card is accepted as written,
but work on it is not authorized yet. When the owner green-lights it, this
card is the working contract and the frozen parameters below are re-read
against the then-current configuration before the run.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Reduction proposal:** `spike-1.9.2-reduction-proposal.md` (accepted
2026-09-12; this card implements its stage 0).
**Supersedes:** task-v1.9.2-7 (Journal real-usage check, absorbed with its
task changed from regression check to damage probe).
**Created:** 2026-09-12.
**Current boundary:** Local-only damage/inertness probe over real Journal
turns. One revision arm, no critic, no integrator, no splits, no cloud, no
GLM checker, no runtime change. Everything below is frozen before the first
revision runs.

## Question

Does one independent local revision pass damage correct answers on the real
request distribution, and how often does it change anything at all? This is
the cheapest decisive question for the ladder: damage kills it regardless of
repair value; inertness at the default prompt means no repair experiment yet.

## Frozen parameters (approved with the proposal)

- **Sample:** approximately 30 completed Journal turns, selected by a
  predeclared rule from the period ending at protocol freeze, sorted by
  timestamp, evenly spaced (same `floor((i+0.5)*N/30)` scheme as card 7 used
  for 6; record N and exclusions). Eligibility: no tool execution, no media,
  no dependence on retrieved history or memory, packet trivially
  reconstructible; text-mode answers only, with the response mode hand-marked
  by the owner during pre-marking (schema gap filed in
  `tasks/bug_reports/2026-09-12-journal-turn-does-not-record-response-mode-or-reasoning-level.md`;
  the reasoning-level requirement is dropped from the selection record).
- **Pre-marking:** the owner marks each selected published answer
  correct/not-correct BEFORE any revision output exists; only
  pre-marked-correct turns are revised and scored for damage. Turns judged
  not-correct are recorded and excluded from the damage denominator.
- **Revision pass:** one pass, local model, current effective settings,
  first-person framing text from the spike card's Revision A contract
  (`task-v1.9.2-1`), applied over the reconstructed evidence packet (original
  request + trivially reconstructible source material) and the labeled
  published answer as D. Same seed (19200) as development elsewhere; same
  seed is control, not a GPU reproducibility promise.
- **Operational definitions (frozen):** damaged = introduced defect of
  severity material or critical (material = wrong result, lost constraint, or
  consequential caveat dropped; critical = unacceptable for the hypothetical
  consequence); minor change = presentation nuisance not changing a required
  result, counted and reported separately, never entering the stop rule;
  substantive change = any change that is not minor, whether for better or
  worse.
- **Scoring:** human only, per turn: unchanged / minor change / improved /
  damaged, with a short reason. Labels compare the revision against the
  pre-marked-correct published answer.
- **Owner time, two slots:** pre-marking ~30 minutes, scoring ~40 minutes.
- **Local call ceiling:** 30 revision calls; no retries beyond the ledger's
  explicit-resume rule; no cloud calls.
- **Privacy boundary:** all Journal content stays local; no cloud packet of
  any kind in this stage. Raw outputs under
  `manual_check_answer_revision_out/<run-id>/`, covered by the existing
  ignore rule.

## Stop rule (predeclared; evaluated on complete turns only)

| Outcome | Reading | Next step |
| --- | --- | --- |
| Damaged >= 3 of 30 | Revision degrades correct answers at a material rate | Stop. Ladder rejected on the real request distribution |
| Damaged 1-2 of 30 | Signal present, sample too small to size it | One bounded damage-only follow-up: its own card, stage-0 format, fresh run-id, same frozen eligibility/scoring, updated revision prompt if the owner directs one |
| Damaged 0 and unchanged >= 25 of 30 | Inert at these settings and with this prompt | Cheap exploratory refinement of the revision instruction (no held-out claim depends on it), then re-run this card once with a fresh run-id before any stage-1 decision |
| Damaged 0 and changes substantive | Safe enough to be worth measuring repair | Stage 1 (deferred cards become active, with a fresh G0) |

A turn that cannot be assessed (evidence gap, ambiguous scoring) is recorded
as not-assessable and leaves the denominators; it is never counted as
unchanged. Damage found by a revision that misread an incomplete packet is
reported separately from mechanism damage, using the reconstruction-fidelity
note kept per turn.

## Agent deliverables

1. A small local-only harness (separate from the deferred card-3 harness;
   no cloud module, no calibration, no splits): sampling rule over the
   Journal read API, packet reconstruction for eligible turns, one revision
   dispatch per turn, raw artifact persistence, and the scoring template -
   pure-tested per the project gates, no live inference in tests.
2. The frozen sampling handoff: exact commands, the selection rule, the
   pre-marking sheet, and state-independent setup steps.
3. `tasks/v1.9.2-stage0-stop-rule.md` (or a section in the report skeleton)
   restating the frozen table above verbatim as the record the human scores
   against.

## Boundary

- No critic, integrator, second baseline, splits, rubrics, or cloud anything.
- No runtime change; the Journal schema gap is the bug report, not this task.
- No prompt tuning in this protocol version except the single exploratory
  refinement explicitly authorized by the inertness row, which resets the
  run with a fresh run-id and never touches stage-1 held-out claims.
- Infrastructure errors stop per AGENTS.md.

## Verification

- `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`
  green; pure tests cover sampling indices, eligibility filtering, packet
  reconstruction shape, dispatch ledger semantics, and template generation.
- Human-run: sampling handoff executed; pre-marking and scoring sheets
  complete; ledger shows 30/30 terminal statuses, no silent retry.
- Outcome recorded against the stop rule with denominators (eligible, marked
  correct, scored, not-assessable), then stop for the owner's decision.

## Acceptance criteria

- [ ] Sampling rule followed with recorded N/exclusions; no answer-based
      replacement; mode hand-marked during pre-marking.
- [ ] All labels judged against the frozen definitions; minor changes
      reported separately and excluded from the stop rule.
- [ ] Stop-rule outcome stated with denominators and the raw artifact
      locations; no threshold reinterpretation after seeing outputs.
- [ ] Local-only enforced end to end; no Journal text in any artifact beyond
      the machine.
- [ ] Stop for human review before any stage-1 work or follow-up run.