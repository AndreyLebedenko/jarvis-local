# Task v1.5.1-2: Resolve the stale pywebview crash guard

**Status:** Ready.
**Story:** `tasks/story-v1.5.1-stabilization.md`
**Source card:**
`tasks/backlog/status-console-api-stale-pywebview-crash-guard.md`
(promoted into this release; execute it as written there, with the
pointers below).

## Summary

Confirm whether `StatusConsoleApi`'s "log a warning and silently return,
never raise" pattern is still justified after the v1.2.10 pywebview
bridge removal, and either remove it in favor of consistent
transport-layer validation or re-document the real reason it stays.

## Context you need

- The backlog card: full history, approaches, and its own stop condition.
- `src/jarvis/ui/status_console.py`: the guard sites
  (`set_visibility_mode()` around line 583, `reset_module()`,
  `set_reasoning_level()`), and the closed-loop guard comment around
  line 560.
- `src/jarvis/ui/transport.py`: `ControlApi` protocol (line ~230) and the
  WS control dispatch that is now believed to be the only caller;
  `ProtocolError` rejection already exists for `set_reasoning_level` one
  layer up.
- `tests/test_status_console.py`: the closed-loop pywebview crash
  regression tests (around lines 281, 495, 1266) whose framing must be
  updated to match whichever outcome this task lands.

## Boundary

- Investigation plus one of the two documented outcomes; no behavior
  changes beyond the guard removal itself.
- If the guard is removed, rejection behavior must remain: transport-layer
  `ProtocolError` validation becomes the single rejection point,
  consistent with what v1.3.1 task 3 already did for
  `set_reasoning_level`.

## Acceptance criteria

- [ ] Verified that no `webview.create_window(...)` site passes `js_api`
      bound to `StatusConsoleApi` (or any equivalent direct JS bridge),
      by grep plus reading every window-creation call site.
- [ ] Either the silent-reject pattern is removed from all three methods
      with docstrings/comments and the regression tests updated, or the
      guard's documentation names the actual reachable path that still
      justifies it - no stale justification remains either way.
- [ ] `python -m pytest`, `python -m ruff check .`,
      `python -m ruff format --check .` green.

## Stop conditions

- Stop if a live pywebview `js_api` path into `StatusConsoleApi` is found
  that static inspection cannot rule out - verify with a live check
  (human-run, real WebView2 window) before removing the guard.
