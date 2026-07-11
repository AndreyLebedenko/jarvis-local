# Story: Quality tooling and package layout

**Status:** In progress.
**Release:** Maintenance.

## User-facing goal

Keep Jarvis inexpensive and safe to change as the codebase grows: automated
checks expose concrete quality regressions, and production source code lives in
an installable `src/jarvis` package organized by responsibility instead of as
unrelated modules in the repository root.

## Boundaries

- Preserve runtime behavior and configuration compatibility.
- Adopt `src/jarvis` and `python -m jarvis` as the canonical package layout and
  launch command.
- Move code in independently verifiable subsystem slices; do not combine the
  migration with behavior changes or opportunistic refactoring.
- Ruff becomes the deterministic lint and formatting tool after the existing
  baseline is made green.
- Complexity checks begin with measured evidence. A blocking threshold is only
  enabled after existing violations are handled explicitly.
- Pyright and Semdup are evaluated separately before either becomes a required
  check. Semdup remains advisory until its false-positive rate is known.
- Radon is not adopted during the initial tooling work: its measured baseline
  adds no actionable signal beyond Ruff `C90`. It remains a future option for
  maintainability-index or aggregate complexity reporting.
- Quality tools are development/CI dependencies, never Jarvis runtime
  dependencies.
- Hardware-dependent checks remain human-run under the existing project
  verification contract.

## Acceptance Criteria

- [ ] The repository has documented, reproducible lint, format, complexity,
      type-checking, and semantic-duplication decisions.
- [ ] Ruff lint and format checks are green and enforced in CI.
- [ ] Production Python code is under `src/jarvis`, grouped by responsibility.
- [ ] `python -m jarvis` is the documented canonical launch command.
- [ ] Tests and manual check scripts import the installed package rather than
      relying on root-level production modules.
- [ ] Pure automated tests remain green throughout the migration.
- [ ] `PROJECT.md` records the package boundary and quality-tooling contract.

## Task Card Sequence

1. `tasks/done/story-quality-task-1-tooling-baseline.md`
   Establish measured Ruff, complexity, Pyright, and Semdup baselines and
   commit the approved deterministic tooling configuration.
2. `tasks/done/story-quality-task-2-package-skeleton.md`
   Add packaging metadata, `src/jarvis`, and the canonical module entry point.
3. `tasks/done/story-quality-task-3-core-and-dialog-migration.md`
   Move core contracts, configuration, backend, and dialog state.
4. `tasks/done/story-quality-task-4-audio-and-input-migration.md`
   Move audio, TTS, capture, clipboard, and hotkey integrations.
5. `tasks/story-quality-task-5-ui-and-composition-migration.md`
   Move UI modules and the application composition root; remove root-level
   production-module compatibility paths.
6. `tasks/story-quality-task-6-tests-manual-and-docs.md`
   Normalize test/manual imports and update README, CI, Graphify, and
   `PROJECT.md`.
7. `tasks/story-quality-task-7-repository-formatting.md`
   Apply Ruff formatting as one isolated mechanical change after moves are
   complete, preserving readable file history during the migration.
8. `tasks/story-quality-task-8-advisory-tool-evaluation.md`
   Evaluate Pyright and Semdup on the final layout and decide their future
   enforcement status from recorded evidence.

## Stop Conditions

- Stop if a move exposes a circular dependency.
- Stop if maintaining runtime compatibility requires temporary duplicate
  modules or import aliases.
- Stop if a quality rule demands behavior changes or broad refactoring outside
  the active task.
- Stop if tool installation or execution fails because of the environment.
