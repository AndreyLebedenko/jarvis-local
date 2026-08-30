# Story: AI pre-commit review gate (fresh-context LLM reviewer behind git hooks)

**Status:** Proposed. No task cards opened yet.
**Created:** 2026-08-30.
**Origin:** the handoff incident
(`tasks/bug_reports/2026-08-30-handoff-silently-depends-on-undocumented-hotkey.md`)
plus the static pre-commit checker shipped in the same investigation
(`tools/check_handoff_self_sufficiency.py`,
`tools/install_handoff_hook.ps1`). Owner analysis (2026-08-30): one hook per
discovered violation class is brittle and permanently one novel defect
behind; root cause of the incident was a *self-review blind spot* - the same
agent wrote and reviewed the handoff, and every existing gate (Codex
stop-time reviews, code review, ruff, pytest) verifies code and tests, never
handoff executability or cross-boundary debt. The fix class is therefore not
another regex, but an independent fresh-context reviewer invoked at the
deterministic commit event.

## User-facing goal

Every commit touching `tasks/**.md` (first slice; charter may extend) is
reviewed by an independent LLM with fresh context before the commit lands.
Violations block the commit; a recorded override preserves the audit trail.
The gate works when the agent is lazy, incentivized to pass, or simply
wrong - its trust assumptions are adversarial to the author by design.

## Design decisions (owner-confirmed 2026-08-30)

- **Blocking with recorded override, not advisory.** A finding blocks the
  commit; the developer either fixes it or commits with an explicit
  trailer. Rationale: agents learn to ignore advisory-only gates, which
  re-creates the "depends on discipline" failure this story exists to end.
- **The override records exactly what was overridden** (owner request).
  Mechanism: `pre-commit` runs the review and writes the verdict (findings
  with stable local ids: file, line, rule, evidence, severity) to a state
  file under `.git/`; a paired `commit-msg` hook rejects the commit if
  findings exist and the message lacks
  `Handoff-Review-Override: <finding ids, verbatim>; reason: <mandatory
  non-empty text>`. The hook validates cited ids against the verdict file
  of the same commit attempt (a reject-and-retry re-runs the review, and
  the retry's verdict is authoritative), so "override everything" without
  citing specifics is rejected, and the commit message carries the exact
  findings and the human-readable why. Edits to the message file by hooks
  are explicitly not relied on - reject-and-paste keeps the mechanism inside
  documented hook guarantees.
- **Model ladder with explicit, announced degradation.** Codex CLI
  (`codex exec`, subscription-backed; also the project's established
  judge in stop-time reviews) -> local `gpt-oss:20b` via the owner's local
  Ollama (full weights, no subscription dependency, chosen as fallback by
  the owner after noting the concern that smaller quants show regular
  false positives on nuance judgments) -> the static heuristic checker
  (`tools/check_handoff_self_sufficiency.py`, stays - it is the
  always-available rung and covers the known class in milliseconds).
  Each run records and prints which rung served and on which
  endpoint/model; an infrastructure error (including the AGENTS.md `Codex`
  section stop rules) degrades the ladder with a loud notice - it never
  blocks the commit by itself and never silently equals "pass".
- **A separate REVIEWER.md charter; the reviewer trusts no self-reported
  status.** `Status: Completed`, `[x]` checkboxes, "VERIFIED", "APPROVED",
  and reviewer-passage claims in cards or summaries are the author's
  assertions, not evidence. Evidence is a citation from the staged diff,
  tests, or source at file:line. When the reviewer cannot verify, it emits
  an explicit unevidenced-claim/cannot-verify finding - never a pass.
  Fresh context every run: the charter is loaded each time; nothing else
  about the author's reasoning is.
- **Static findings get canonicalized.** A reviewer finding that recurs
  across commits is promoted into the static checker (the dynamic layer
  graduates rules into the fast layer). The static checker is not deleted
  or demoted.

## Boundaries

In scope:

- REVIEWER.md (the charter: trust rules, review scope, verdict contract).
- The reviewer engine: context assembly, model ladder, verdict parsing,
  state-file handoff between pre-commit and commit-msg, provenance output.
- Hook integration (pre-commit + commit-msg) extending the existing
  installer pattern (`tools/install_handoff_hook.ps1`), coexisting with
  graphify hooks.
- Pure tests for everything testable without a live model (context
  assembly, verdict parsing, override validation, ladder degradation with
  fake runners).
- A human-run calibration + live handoff.

Out of scope:

- Making the reviewer review `src/**` code quality - that duplicates the
  existing human-triggered Codex/code-review workflow; the gate reviews
  process-contract compliance (handoff executability, debt crossings,
  unevidenced claims), not code style.
- CI enforcement on push (blocks bypassing via `--no-verify`). Deliberately
  an owner decision, not a default here: current CI contract is
  "requirements + pytest only". Recorded as a follow-up decision, not
  silently dropped.
- Any change to the runtime locality contract: the review gate is an
  agent/dev tool (graphify precedent), runs only at commit time on the dev
  machine, and its network use (Codex, or a subscribed Ollama endpoint) is
  reported in its output per the project's data-source honesty habit. This
  must be stated in PROJECT.md when the story lands, so the reviewer's
  egress can never be misread as a Jarvis runtime property.

## Open decisions (resolved inside task 1, with the owner if needed)

- How the active task card is made machine-discoverable for context
  assembly: proposal - the agent exports `JARVIS_ACTIVE_TASK=<path>` in its
  commit flow; absence is reported honestly ("reviewed without task-card
  context"). A committed pointer file was rejected in principle (per-task
  commit noise); a repo-state heuristic is fragile. Owner to bless the env
  convention or pick the alternative.
- Whether review runs on every commit or only commits whose staged diff
  touches `tasks/**.md` (proposal: scope-gated for the first slice; the
  charter names the extension path).
- Latency budget: proposal - `codex exec` with a hard timeout (default
  120 s), timeout degrades to the next rung with a notice.

## Scope (ordered task cards, to be opened one at a time)

1. **REVIEWER.md + verdict contract.** The charter document (trust
   hierarchy, anti-claim rules, review scope, output JSON schema with
   findings/ids/severity/evidence/cannot-verify categories) and a pure
   parser/validator for that schema. Machine-readability of the active
   task context resolved here (env convention or alternative). No hook,
   no model call yet.
2. **Reviewer engine.** `tools/commit_reviewer.py`: context assembly
   (staged diff, AGENTS.md, REVIEWER.md, REVIEWER.md-referenced task card),
   model ladder with fake-runner seams (Codex, local gpt-oss:20b, static
   fallback), verdict parsing/validation, retry-once-then-degrade policy,
   provenance lines. Pure tests with fake runners cover: ladder order,
   degradation announcements, malformed-verdict handling, static-rung pass
   through. No hook wiring yet.
3. **Hook integration + override trailer.** pre-commit (review -> state
   file -> violations block) and commit-msg (override validation, id
   checking against the fresh verdict, reject-and-paste UX). Extends
   `tools/install_handoff_hook.ps1` (BOM-less sh output, single-block
   refresh, coexistence rules). Pure tests for the override protocol.
4. **Calibration + live handoff.** Owner-run: rerun the reviewer against
   the seven known legacy violations (the static checker's earlier full-tree
   findings), the two repaired v1.9.0 cards (must pass), and a sample of
   recent clean commits (should pass); a synthetic "TRUSTMEBRO" card
   claiming verification without tests must be flagged as an unevidenced
   claim. Owner records FP/FN; prompt/model/charter changes land only with
   those recorded numbers. If FP rate at the gpt-oss rung is unacceptable
   and Codex is unavailable - stop and re-decide the gate with the owner.
5. **Docs + PROJECT.md note.** PROJECT.md entry framing the gate as
   agent/dev tooling with reported egress (graphify precedent), README
   dev-workflow note, `AGENTS.md`/`CLAUDE.md` Testing-protocol pointer to
   the gate and the override trailer convention.

## Acceptance criteria

- [ ] A staged commit reintroducing the original defect (handoff referencing
      an undocumented hotkey) is blocked by both the static rung and the
      LLM rung; the static rung alone still blocks it with both model rungs
      unavailable.
- [ ] A clean commit passes; hook output names the serving rung, the
      model/endpoint, and the duration; neither model rung being reachable
      ever renders as an unmarked pass.
- [ ] Override path: a bare override attempt without reason or with unknown
      finding ids is rejected; a valid override lands a trailer in the
      commit message quoting verbatim finding ids and the reason, and the
      trailer is greppable from history.
- [ ] A staged card asserting "VERIFIED"/"[x] Completed" without test or
      diff evidence is flagged by the reviewer as an unevidenced claim
      (charter rule proven live, not only by prompt inspection).
- [ ] `python -m pytest` and ruff gates green for all pure parts; the live
      calibration handoff is prepared with exact commands and its FP/FN
      numbers recorded before the gate is trusted.
- [ ] PROJECT.md and README document the gate's dev-tooling status and
      output provenance; the runtime locality contract is untouched.

## Stop conditions

- Stop if the calibration shows the non-Codex rungs produce unacceptable
  false-positive rates (blocking honest work regularly): re-decide the gate
  mode with the owner rather than shipping a noisy blocker.
- Stop if `codex exec` non-interactive runs hit the AGENTS.md `Codex`
  infrastructure rules (approval/logon-session failures): report and stop;
  do not route around the mechanism.
- Stop if hook message-editing semantics would be required beyond
  reject-and-paste to implement the override record - that means the design
  leans on undocumented git behavior; fall back to reject-and-paste or ask.
- Stop if context assembly cannot obtain the staged diff reliably in real
  git workflows (merge commits, partial staging, fixups) without fragile
  parsing - report and scope that as its own problem.