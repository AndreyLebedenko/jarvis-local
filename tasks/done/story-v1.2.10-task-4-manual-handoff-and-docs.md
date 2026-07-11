# Task: UI transport manual handoff and documentation

**Story:** `tasks/story-v1.2.10-ui-transport.md`
**Status:** Completed.
**Release:** v1.2.10

## Summary

Prepare the human-run verification for the migrated surfaces (real WebView2
windows plus a Chrome client) and record the transport decision and loopback
guarantee in project documentation.

## Current Boundary

- Update `manual_check_status_console.py` (and touchstrip manual check if
  separate) to start the real server, open real windows on the loopback
  URL, and drive real states. The agent writes the script and exact
  commands; the human runs them.
- Manual checklist includes: visual parity for console and touchstrip
  against pre-migration behavior, all four control actions, WS reconnect
  after killing/restoring the server, and the same URL plus token opened in
  Chrome with working state display and controls.
- Documentation updates in the same change:
  - `PROJECT.md`: transport decision (local aiohttp HTTP+WS server, protocol
    v1 with hello/state/control), and the locality clarification - listening
    on loopback is not outbound network access; the runtime guarantee
    "no network beyond the configured local Ollama endpoint" is unchanged.
  - `tasks/roadmap-v1.2-v1.4.md`: v1.2.10 marked complete when done.
- No new features; only verification and documentation.

## Acceptance Criteria

- [x] Manual check script starts server plus windows in the correct order
      and exercises every checklist item with exact human-run commands.
- [x] Automated tests cover the script's bus/server wiring without a real
      window (mirroring `tests/test_manual_check_status_console.py`).
- [x] `PROJECT.md` records the transport decision and loopback guarantee.
- [x] `python -m pytest` passes.
- [x] Human has confirmed the manual checklist; results recorded before the
      story closes.

## Outcome

Human verification accepted the migrated Status Console and touchstrip on
2026-07-11. The automated suite passed with 479 tests. The same session found
the separate MME microphone restart failure after sleep/wake; it is recorded
in `tasks/bug_reports/microphone-wake-portaudio-restart-failure.md` and is
outside this UI transport handoff.

## Stop Conditions

- Stop if manual verification reveals visual or behavioral regressions -
  report per bug-report protocol instead of patching ad hoc.
- Stop if Chrome and WebView2 render or behave differently in a way that
  requires surface-specific code.
