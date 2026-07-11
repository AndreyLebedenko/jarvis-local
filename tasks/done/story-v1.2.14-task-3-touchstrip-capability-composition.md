# Task: Replace TouchstripWindow NotImplementedError overrides with capability composition

**Story:** `tasks/story-v1.2.14-ui-state-foundation.md`
**Status:** Completed (obsolete: resolved by the v1.2.10 bridge removal,
verified 2026-07-11). No code change was made under this card.
**Release:** v1.2.14
**Origin:** Entropy-review of v1.2.4/v1.2.5 code (2026-07-09).
**Note:** file references below predate the src/jarvis package move and
describe the pre-v1.2.10 bridge architecture.

## Closure note (2026-07-11)

The defect this card describes no longer exists. The v1.2.10 UI
transport migration deleted the `push_*` bridge methods entirely;
`StatusConsoleWindow` is now a pure window shell and `TouchstripWindow`
overrides only constructor configuration (title, URL, geometry) - a
legitimate specialization, not contract narrowing. Verified by
repository-wide search: no `NotImplementedError` capability overrides,
no `_status_surfaces()` remain. Per-surface content routing now lives in
the web clients (touchstrip.js renders its subset of the state channel),
where there is no inheritance contract to violate.

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

- [x] No `NotImplementedError` capability overrides remain (already true
      before this card ran - see Closure note).
- [x] Existing per-surface routing behavior is unchanged (touchstrip
      still receives no system events / config menu pushes).
- [x] `python -m pytest` passes.
