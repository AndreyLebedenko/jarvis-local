# Task: Enforce Ruff quality gates in CI

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Extend GitHub CI with the deterministic quality checks that are now green:
Ruff formatting and Ruff lint/complexity.

## Current Boundary

- Keep CI limited to the pure automated suite.
- Install development-only tooling from `requirements-dev.txt`.
- Run `python -m ruff format --check .`.
- Run `python -m ruff check .`.
- Keep `python -m pytest` as the test command.
- Do not add Pyright, Semdup, Radon, Graphify extraction, live Ollama, secrets,
  model downloads, or hardware-dependent checks in this task.

## Acceptance Criteria

- [x] GitHub CI installs the dependencies needed for Ruff and pytest.
- [x] GitHub CI runs Ruff format check before tests.
- [x] GitHub CI runs Ruff lint/complexity check before tests.
- [x] GitHub CI still runs `python -m pytest`.
- [x] Local verification passes:
      `python -m ruff format --check .`,
      `python -m ruff check .`, and
      `python -m pytest`.
