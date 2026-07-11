# Task: Establish quality-tooling baseline

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Completed.
**Release:** Maintenance.

## Summary

Measure the current repository with candidate quality tools, choose a small
deterministic Ruff rule set, and add the configuration and development
dependencies needed to reproduce the accepted baseline. Do not move source
files or refactor production behavior in this task.

## Current Boundary

- Add `pyproject.toml` only for development-tool configuration; packaging is
  Task 2.
- Add pinned-compatible adopted development dependencies to
  `requirements-dev.txt`; evaluation-only tools are not retained.
- Run Ruff lint and format checks, evaluate complexity with Radon once, and run
  Pyright as a non-blocking evaluation.
- Run a local Semdup scan if its standalone installation and model acquisition
  work normally; otherwise record the environmental blocker and stop rather
  than work around it.
- Fix only mechanical Ruff findings that do not alter behavior.
- Record deferred complexity/type/duplication findings in this card.
- Do not change CI in this task; enforcement follows only after a green local
  baseline is reviewed.

## Acceptance Criteria

- [ ] Candidate tools and versions are reproducible from project files.
- [ ] Ruff rule selection and test-specific exceptions are explicit.
- [ ] Ruff lint and formatting checks pass, or existing findings are recorded
      precisely for a later bounded task.
- [ ] Complexity hotspots are recorded with symbol and score.
- [ ] Pyright and Semdup outcomes are recorded without making them gates.
- [ ] `python -m pytest` passes.

## Verification

- `python -m ruff check .`
- `python -m ruff format --check .`
- One-time evaluation: `python -m radon cc -s -a .`
- `python -m pyright`
- `python -m pytest`

## Stop Conditions

- Stop if the chosen Ruff rules require non-mechanical production refactoring.
- Stop on dependency installation or tool execution infrastructure errors.
- Stop if baseline failures reveal behavior defects outside this task.

## Baseline Findings (2026-07-11)

- Ruff 0.12.12 default lint: 48 findings. Of these, 42 are `E402` caused by
  manual scripts inserting the repository root into `sys.path`; the package
  migration is the correct fix. The remainder is five unused imports and one
  lambda assignment in a test.
- Ruff format check: 42 files would be reformatted. Applying this would be a
  repository-wide diff outside this task's mechanical-change boundary.
- Radon 6.0.1 reports no function at complexity 8 or higher with its standard
  cyclomatic-complexity calculation. The earlier ad-hoc AST estimate was more
  conservative and is not used as the project baseline.
- Decision: do not add Radon to the project's development dependencies or CI
  at this stage. Its baseline found no actionable hotspot and therefore adds
  no signal beyond the planned Ruff `C90` check, while introducing another
  dependency, configuration surface, and potentially conflicting complexity
  calculation. Reconsider Radon only if Jarvis later needs maintainability
  index, aggregate/module complexity budgets, or trend reporting that Ruff
  cannot provide.
- Pyright 1.1.411 reports 203 errors across production, tests, and manual
  checks. Many arise because injected fakes are typed as concrete classes
  rather than protocols; making Pyright green requires a separate design task,
  not baseline suppression.
- The baseline reached the task stop condition: adopting Ruff formatting now
  is wide-ranging, while enforcing default lint before package migration would
  either require temporary suppressions or preserve the `sys.path` workaround.

## Adopted Ruff Baseline

- Ruff 0.12.x is the only retained quality-tool dependency. Configuration is
  centralized in `pyproject.toml` for Python 3.11 with lint families `B`, `C4`,
  `C90`, `E`, `F`, `I`, `RUF`, `SIM`, `UP`, and `W`.
- Complexity ceiling: `C901 <= 10`. Existing exceptions are not suppressed:
  `audio_in.run_microphone_loop` scores 14 and
  `ui_transport._dispatch_control` scores 12. They remain visible work for a
  bounded redesign rather than becoming permanent ignores.
- The expanded configured scan reports 312 findings: 217 `E501`, 54 `RUF001`,
  15 import-order findings, 5 unused imports, 2 complexity findings, and 19
  other modernization/simplification findings. These are baseline inventory,
  not a green gate. Formatting is isolated in Task 7; migration tasks remove
  import-path workarounds before lint enforcement.
- `RUF001` includes canonical Russian runtime strings, which project policy
  explicitly treats as data. The later lint-enforcement task must scope this
  rule without rewriting those strings.
- Ruff's `B023` finding in `tests/test_audio_in.py` is a loop variable captured
  by a lambda that is awaited to completion inside the same iteration. It is
  safe in the current control flow, but remains inventory for the later
  mechanical lint cleanup.
- Verification: `python -m pytest` passes all 526 tests. Ruff lint and format
  checks intentionally remain red with the recorded baseline until their
  scheduled tasks.
