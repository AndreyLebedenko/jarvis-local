# Backlog: Verify StatusConsoleApi's "never raise" guard is still needed

**Status:** Backlog.
**Source:** story-v1.3.1 task 3 review (2026-07-13), while deciding how
`StatusConsoleApi.set_reasoning_level()` should reject an unknown level.

## Summary

Confirm whether `StatusConsoleApi`'s defensive "log a warning and silently
return, never raise" pattern (`set_visibility_mode()`, `reset_module()`, and
now `set_reasoning_level()`) is still justified, or whether its original
reason has been obsolete since the v1.2.10 pywebview bridge removal - and if
so, consider removing it in favor of consistently raising.

## Context

The pattern's documented reason (see `set_visibility_mode()`'s comment and
the "closed-loop pywebview crash" regression test) is that raising from
these methods used to be able to crash pywebview's own JS-API dispatch
thread, verified live on 2026-07-07.

While implementing `set_reasoning_level()` for story-v1.3.1 task 3, I
checked `StatusConsoleWindow.create()` (`status_console.py`) and found it
calls `webview.create_window(...)` with no `js_api=` argument at all. That
matches the v1.2.10 story's bridge removal (`story-v1.2.10-task-3-
touchstrip-migration-and-bridge-removal.md`): `StatusConsoleApi` now
appears to be reachable only as `UiTransportServer`'s `ControlApi`, through
`_dispatch_control()` on the WS control-command path - not directly from a
pywebview JS thread anymore. If that holds everywhere, the original crash
condition may no longer be reachable, and the silent-reject pattern is
carrying a stale justification.

I did not chase this further inside task 3 - it is not blocking, and task 3
already added real `ProtocolError` rejection for `set_reasoning_level()` one
layer up, in `UiTransportServer._set_reasoning_level()`, so the product
behavior is correct regardless of this question.

## Current Boundary

- Not blocking story-v1.3.1; do not fold into any of its remaining tasks.
- Do not change `set_visibility_mode()` or `reset_module()`'s behavior
  without first confirming the bridge is really gone everywhere.

## Possible Approaches

- Grep/confirm no window-creation path in the codebase still passes
  `js_api=` pointing at a `StatusConsoleApi` instance.
- If confirmed dead: remove the silent-reject try/except from
  `set_visibility_mode()`, `reset_module()`, and `set_reasoning_level()`,
  let them raise, and rely on transport-layer `ProtocolError` validation
  consistently (matching what task 3 already does for
  `set_reasoning_level()`). Update the stale docstrings/comments and the
  "closed-loop pywebview crash" regression test's framing.
- If a live pywebview JS call path is found: keep the guard, but tighten
  the comment to name the actual reachable path instead of the historical
  one.

## Acceptance Criteria

- [ ] Confirms whether any `webview.create_window(...)` call site still
      binds `js_api` to `StatusConsoleApi` (or an equivalent direct JS
      bridge).
- [ ] Either removes the now-unjustified silent-reject pattern, or updates
      its documentation to name the real reason it is still needed.
- [ ] `python -m pytest` passes.

## Stop Conditions

- Stop if pywebview still has an active direct JS-API path into
  `StatusConsoleApi` that isn't obvious from a static grep - verify with a
  live check before removing the guard.
