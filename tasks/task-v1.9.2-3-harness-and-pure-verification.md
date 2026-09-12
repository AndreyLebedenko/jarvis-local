# Task v1.9.2-3: Harness and pure verification

**Status:** Deferred 2026-09-12. Retained as the draft of stage 1 (repair
measurement) under the accepted reduction proposal
(`spike-1.9.2-reduction-proposal.md`); the CLI contract, ledger, cloud helper
and scoring plumbing described here belong to stage 1. Stage 0 (card
v1.9.2-9) uses its own smaller local-only harness with a separate card.
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Spike card (contract source):** `task-v1.9.2-1-local-answer-revision-spike.md`, Phase 1.
**Depends on:** task-v1.9.2-2 (protocol, corpus, sidecar, egress manifest exist).
**Created:** 2026-09-12.
**Current boundary:** Implement the offline harness, its CLI contract, and its
pure tests. No live local or cloud inference is executed by the agent; all
`run` and `score-cloud` commands are human-run in later cards.

## Summary

Implement the developer-only manual harness that drives the spike: the CLI
entry point, request composition from project config, the run ledger with
resume semantics, scoring plumbing, and the report path - all verified by pure
tests against fixtures and fake clients.

## Deliverables

1. `manual/manual_check_answer_revision.py`: human-run entry point following
   the `python -m manual.manual_check_*` convention. Subcommands exactly as
   the spike card's CLI contract states: `validate`,
   `run --phase pilot-framing|pilot-continuation|held-out|journal`,
   `score-cloud --run-id ... --approve-manifest ...`, `select-framing`,
   `freeze`, `report`. The pilot is split into two phases with an explicit
   framing-selection seam: `select-framing` applies the frozen rule to the
   scored sheets, records the choice and its provenance (measured or
   tiebreak) into the run ledger and protocol sidecar, refuses to run while
   decisive sheets are unscored or disputed, and is offline; the held-out
   `run` reads the selected framing from the sidecar and fails validation if
   absent. Adjust the spike card only if the implemented parser needs a
   different approved contract.
2. `manual/answer_revision_cloud_checker.py`: isolated cloud transport module
   for the GLM checker, never imported directly or transitively by
   `src/jarvis` (enforced by a pure test).
3. Run ledger under `manual_check_answer_revision_out/<run-id>/`: run/case/
   arm/repeat/stage IDs, hashes, options, timestamps, terminal status, exact
   permitted packets/results. Terminal results immutable; `--resume` skips
   completed IDs; no automatic retry of uncertain requests; interrupt stops
   future dispatches.
4. Report generation producing `tasks/v1.9.2-spike-report.md` skeletons from
   ledger data.

## Contract details (from the spike card; implement literally)

- Local endpoint/model/options come from project config loading. The executor
  must reject a `:cloud` model selection or a public endpoint (pure-tested).
  No model downloads, service starts, or GPU probes.
- 4096-token generated-output cap per local call as a resource ceiling; cap
  hits recorded as incomplete outcomes, not valid short answers.
- Stage timeouts: 120 s local, 90 s cloud. Seeds come from the protocol
  sidecar as the single authoritative enumeration (19200 development, 19201
  and 19202 held-out repeats, 19203 Journal revision, 19204 audit sampling at
  the time of writing); the harness reads them from the sidecar, not from a
  card's prose.
- All `message.thinking` discarded; only task outputs and numeric timing/token
  metadata retained.
- Authentication uses the documented provider credential mechanism; never
  embedded in arguments, protocol, source, or logs; secret redaction pure-
  tested.
- Cloud allowlist rejection of Journal cases pure-tested.

## Pure test coverage (required)

Composition/isolation of role requests; budgets/caps; deterministic matrix
counts (including the split pilot phases: 24 framing-comparison calls, 18
pilot-continuation calls, 18 injected-diagnostic calls); seed assignment;
scorer parsing; severity/scoring logic; the `select-framing` rule (fewer
introduced material errors, then more corrected defects, ties keep
first-person) and its refusal on unscored/disputed decisive sheets; sidecar
write-back and read-back of the selected framing; interruption and resume; no
duplicate dispatch/publication; secret redaction; no runtime import of the
cloud helper; one fake-client end-to-end functional test exercising all
selected arms and the report path. No test invokes local or cloud inference.

## Boundary

- No production wiring in `src/jarvis`; the harness is disposable.
- No prompt tuning; prompt text comes verbatim from the frozen protocol.
- Infrastructure failures report and stop per AGENTS.md; no shell/model/
  provider change.

## Verification

- `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`
  green.
- `python -m manual.manual_check_answer_revision validate --protocol
  tasks/v1.9.2-spike-protocol.md` runs offline and verifies sidecar hashes,
  manifest structure, and flag parsing; cite each flag's source in the handoff.
- Handoff document for the human lists exact commands, credential name,
  endpoint/default sources, and state-independent setup steps.

## Acceptance criteria

- [ ] CLI contract from the spike card implemented and parser-verified offline.
- [ ] All listed pure tests present and green; zero live inference in tests.
- [ ] Cloud helper not importable from `src/jarvis` (test enforced).
- [ ] Immutable ledger and resume semantics covered by tests.
- [ ] Green pytest/ruff gates; executable human handoff prepared for G0 review.
- [ ] Stop for human review before phase-2 execution is scheduled.