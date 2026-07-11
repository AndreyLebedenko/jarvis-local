# Task: Touchstrip migration and bridge removal

**Story:** `tasks/done/story-v1.2.10-ui-transport.md`
**Status:** Completed.
**Release:** v1.2.10

## Summary

The touchstrip surface migrates to the same WS transport, declaring itself
as a distinct client in the hello handshake. The `evaluate_js`/`js_api`
bridge machinery is then deleted; the server is the only UI transport left.

## Current Boundary

- Touchstrip front-end connects to the same server and the same `state`
  channel; it declares `touchstrip` identity/capabilities in hello so the
  server (or later the orchestrator) can distinguish surfaces.
- Touchstrip stays a glance/control surface; no new controls or panels are
  added during migration.
- After migration, remove: `push_*` methods that call `evaluate_js`, the
  `js_api` object exposure, and any GUI-thread choreography that existed
  only for the bridge. Window creation/lifecycle code stays.
- Tests asserting bridge behavior are removed or rewritten against the WS
  path in the same commit; no dead test code remains.
- If the touchstrip currently shares `status_console.py` plumbing, the
  shared remainder after deletion must still respect SRP (window shell
  versus transport client are separate concerns).

## Acceptance Criteria

- [ ] Touchstrip renders its existing states through the WS transport.
- [ ] Hello handshake carries distinct identities for console and
      touchstrip clients.
- [ ] No production code references `evaluate_js` or `js_api`.
- [ ] `python -m pytest` passes with bridge tests removed/rewritten.

## Verification

- Run `python -m pytest`.
- Real-window checks are part of task 4's manual handoff.

## Stop Conditions

- Stop if touchstrip behavior depends on a bridge feature that has no WS
  equivalent yet.
- Stop if bridge removal would delete code still used outside the UI
  transport path.
