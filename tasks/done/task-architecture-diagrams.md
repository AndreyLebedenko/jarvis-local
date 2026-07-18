# Task: Architecture diagrams and local PlantUML verification

**Status:** Completed.
**Release:** Maintenance.

## Summary

Add maintainable architecture diagrams that explain package responsibilities
and the end-to-end request flow, plus a local developer command that verifies
PlantUML syntax and renders reviewable SVG output.

## Current Boundary

- Keep PlantUML sources under `docs/architecture/`.
- Add a Python standard-library wrapper under `tools/`.
- Download a pinned official PlantUML JAR only through an explicit install
  command and verify its published SHA-256 digest.
- Keep the JAR in an ignored developer cache; do not add it to Jarvis runtime
  dependencies or contact a PlantUML server.
- Add pure automated tests for wrapper logic.

## Acceptance Criteria

- [x] A package responsibility/dependency diagram exists.
- [x] An end-to-end request sequence diagram exists.
- [x] One command verifies all diagram syntax locally.
- [x] One command renders SVG files into a dedicated output directory.
- [x] The PlantUML distribution is pinned and integrity-checked.
- [x] Ruff and the pure automated test suite pass.

## Verification

- `python tools/plantuml.py check`
- `python tools/plantuml.py render`
- `python -m ruff check .`
- `python -m ruff format --check .`
- `python -m pytest`
