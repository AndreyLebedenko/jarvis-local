# Task: Status Console migrates to the WS transport

**Story:** `tasks/story-v1.2.10-ui-transport.md`
**Status:** Planned.
**Release:** v1.2.10

## Summary

The Status Console front-end becomes a WS client of the task-1 server.
`StatusConsoleWindow` is reduced to a window shell that opens pywebview on
the server's loopback URL. Visual behavior does not change.

## Current Boundary

- `status_console_ui/` is served by the server; `app.js` gains a WS client
  (connect, handshake, apply snapshot, apply deltas) that feeds the existing
  `applyRuntimeState`/`applyModuleHealth`/`applyDataLocality`/
  `applyModelLabel`/system-event DOM functions unchanged.
- Console controls (Think toggle, reset, shutdown, visibility) send
  `control` messages instead of calling `window.pywebview.api`.
- `StatusConsoleWindow` keeps its injectable `window_factory` test pattern
  but drops `push_*`/`evaluate_js` responsibilities for the console path;
  it opens `http://127.0.0.1:<port>/?token=...` and owns only window
  lifecycle.
- Touchstrip stays on the old bridge until task 3; both transports may
  coexist inside this task only.
- No markup or CSS changes beyond what the WS client strictly requires.
- Reconnect behavior: on WS drop the console shows its existing degraded/
  offline affordance if one exists, or a minimal non-fake indicator; it must
  not silently show stale state as live.

## Acceptance Criteria

- [ ] Console renders identical states as before migration for every value
      exercised by `demo.html`'s QA harness (harness updated to drive the
      WS path or the same DOM functions directly).
- [ ] All four control actions work through the `control` channel and
      produce the same system events as before.
- [ ] `window.pywebview.api` is no longer referenced by console code paths.
- [ ] Bus-wiring tests updated: fake WS client replaces fake console where
      the old tests asserted `push_*` calls.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Real-window visual parity check is deferred to task 4's manual handoff;
  this task prepares it but does not run it.

## Stop Conditions

- Stop if parity requires markup changes beyond transport wiring.
- Stop if any control action cannot round-trip through the server without
  keeping a `js_api` fallback.
