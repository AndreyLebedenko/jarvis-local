# Task v1.9.2-7: Local Journal real-usage check

**Status:** Planned. Blocked on G2 computation (may run in parallel with the
owner's G2 review only if the owner says so; default is after).
**Story:** `story-v1.9.2-local-generation-critique-integration.md`.
**Spike card (contract source):** `task-v1.9.2-1-local-answer-revision-spike.md`, Phase 5.
**Depends on:** task-v1.9.2-6 (audited held-out outcome).
**Created:** 2026-09-12.
**Current boundary:** Human-run local replay of up to 6 real Journal turns.
Strictly local; no Journal content ever reaches the cloud checker.

## Summary

Replay selected real Journal turns through the selected revision/critique
procedures to check for a practical regression on ordinary use. This is
retrospective replay, not a fresh end-to-end baseline comparison.

## Case selection (predeclared rule; no cherry-picking)

- Up to 6 text-only completed Journal turns from the 14 days preceding the
  protocol freeze, sorted by timestamp.
- Exclude: media, executed tools, missing source evidence, source packets
  that cannot be reconstructed faithfully, and turns whose published answer
  was produced under a response mode other than `text` (a `voice`-mode answer
  revised under the text output contract would measure contract conversion,
  not revision quality; the mode is recoverable from the assistant journal
  event's metadata, which stores the spoken derivative alongside the answer).
- Selection by evenly spaced indices `floor((i+0.5)*N/6)` for N >= 6
  eligible turns; otherwise all eligible turns.
- Record the reasoning level in force for each selected turn alongside N,
  exclusions, and selected references, locally. No replacement based
  on answers. An empty eligible sample means ordinary-use evidence is
  unavailable and is recorded as such.

## Execution and scoring

- Reuse each published answer as D; selected R and C/I cost 3 calls/turn,
  at most 18 local calls (seed 19203 for revision).
- Score locally by the human: improved / tied / damaged / not assessable,
  with a short reason; at most 12 human comparisons. Not-assessable is a valid
  label where ground truth is unavailable.
- Change detection recorded separately from the improvement judgment; a
  change is not automatically an improvement.

## Interpretation limits (predeclared)

- Fewer than 4 assessable turns leaves ordinary-use applicability unmeasured;
  it does not invalidate the separate authored-case result.
- The sample can expose a practical regression but cannot precisely estimate
  a general user error rate; conclusions are limited to the sampled period
  and request population.
- An adjudicated material regression pauses rollout for owner review even if
  G2 passed.

## Boundary

- Local-only: no Journal text in any cloud packet, prompt, or artifact that
  leaves the machine; enforced by the harness allowlist rejection tested in
  task v1.9.2-3.
- No new cases, no substitutions after seeing outputs.

## Verification

- Selection record (N, exclusions, indices) reproducible from the stated rule.
- Complete ledger for at most 18 local calls; human comparison sheets with
  labels and reasons.
- Report section with denominators, unassessable counts, and the explicit
  replay-not-baseline caveat.

## Acceptance criteria

- [ ] Selection followed the predeclared rule; no answer-based replacements.
- [ ] All dispatched calls in the ledger with immutable statuses; no cloud
      egress of Journal data.
- [ ] Comparison judgments recorded with reasons and denominators.
- [ ] Applicability limits (sample size, replay nature) stated in the results.
- [ ] Stop for human review before the final report card.