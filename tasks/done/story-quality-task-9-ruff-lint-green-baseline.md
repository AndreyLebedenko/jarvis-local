# Task: Make Ruff lint baseline green

**Story:** `tasks/done/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Fix the post-format Ruff lint baseline so deterministic lint and complexity
checks can become CI gates.

## Current Boundary

- Keep runtime behavior unchanged.
- Prefer Ruff auto-fixes for mechanical import and modernization findings.
- Treat intentional Russian runtime/test strings as valid project data, not as
  homoglyph mistakes.
- Refactor only the two current `C90` hotspots:
  `AudioInput.run_microphone_loop()` and `UiTransportServer._dispatch_control()`.
- Do not add Pyright, Semdup, or Radon enforcement in this task.

## Acceptance Criteria

- [x] `python -m ruff check .` passes.
- [x] `python -m ruff format --check .` passes.
- [x] `python -m pytest` passes.
- [x] The lint policy documents why `RUF001` is not useful for this codebase.
