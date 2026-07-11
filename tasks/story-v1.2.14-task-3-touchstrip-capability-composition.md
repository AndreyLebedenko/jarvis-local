# Task: Replace TouchstripWindow NotImplementedError overrides with capability composition

**Story:** `tasks/story-v1.2.14-ui-state-foundation.md`
**Status:** Planned. Runs after task 2 so the capability split can also
route the new health events per surface.
**Release:** v1.2.14
**Origin:** Entropy-review of v1.2.4/v1.2.5 code (2026-07-09).
**Note:** file references below predate the src/jarvis package move;
resolve them against the current layout.

## Summary

`TouchstripWindow` subclasses `StatusConsoleWindow` and overrides four
methods (`push_system_event`, `push_model_options`,
`push_microphone_options`, `push_pending_restart`) to raise
`NotImplementedError`. This narrows the base-class contract (LSP
violation): any caller iterating over `_status_surfaces()` must know
which `push_*()` methods are safe on which surface, and a future generic
loop calling a desktop-only push on both surfaces crashes at runtime
instead of failing a type check.

## Proposed direction

Split the surface contract by capability instead of inheritance-with-
holes: e.g. a narrow `GlanceSurface` protocol (runtime state, module
health, model label, locality, thinking/visibility mode) that both
windows satisfy, plus desktop-only methods living on
`StatusConsoleWindow` alone. `LiveStatusConsole` then holds
`glance_surfaces: list[GlanceSurface]` and a single desktop console for
the desktop-only pushes, so "which surface supports what" is expressed
in types, not in raising overrides.

## Acceptance criteria

- [ ] No `NotImplementedError` capability overrides remain.
- [ ] Existing per-surface routing behavior is unchanged (touchstrip
      still receives no system events / config menu pushes).
- [ ] `python -m pytest` passes.
