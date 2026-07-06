# Task UI-03: System events panel

**Story:** story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** высокий
**Зависимости:** [task-ui-01-state-and-event-contract.md](done/task-ui-01-state-and-event-contract.md),
[task-ui-02-desktop-status-console-shell.md](done/task-ui-02-desktop-status-console-shell.md)

## Summary

Expose engine activity in the UI so the user does not need to inspect Windows
console output.

## Scope

- Display recent events in reverse chronological or live-appending order.
- Show timestamp, source, level and message.
- Support sources such as `ENGINE`, `VAD`, `STT`, `LLM`, `TTS`, `CAPTURE`,
  `HOTKEY`, `CONFIG`, `WARMUP`.
- Support levels `INFO`, `ACTIVE`, `WARN`, `ERROR`.
- Keep event text concise and user-readable.

## Stop Condition (resolved before implementation)

If logs and bus events diverge as competing sources of truth, stop and define
which layer owns UI-visible events before implementation.

**Triggered and resolved:** `system_log.py`'s `publish_system_event(bus,
logger, source, level, log_message, ui_message, correlation_id=None)` is the
one call site that decides a user-facing system event happened - it always
logs via the given logger *and* publishes `ui_contract.py`'s `SystemEvent` on
the bus together, so the two can never disagree about whether something
fired. `log_message` (English, matches this project's existing console-log
convention) and `ui_message` (Russian, matches the Status Console's other
text) are deliberately two different strings for two different audiences,
not one string forced to serve both - see `system_log.py`'s docstring for the
full reasoning.

## Implementation

- `system_log.py` - `publish_system_event()`, the single source of truth
  described above. Pure/testable: `tests/test_system_log.py` covers the
  bus-publish, the Python-logging side effect, level mapping
  (`EventLevel.WARN` -> `logging.WARNING`, etc.), and the
  zero-subscribers-is-a-no-op case.
- `main.py` - `warm_up()` (now takes `bus: EventBus`), `_on_mic_sleep_
  toggled()`, and `_on_thinking_mode_toggled()` now call
  `publish_system_event()` at their existing log call sites (sources
  `WARMUP`/`HOTKEY`), in addition to (not instead of) `warm_up()`'s
  existing `logger.exception()` full stack trace on failure. All existing
  `test_main.py` assertions on the English log text are unchanged; new
  tests assert the matching `SystemEvent` is published.
- `status_console_ui/app.js` - `appendSystemEvent()` renders a new
  `.log-entry` (timestamp/source/message), newest-first
  (`Element.prepend()`), capped at `MAX_LOG_ENTRIES = 200` DOM nodes.
  `index.html`'s events panel is real now (`#logList`), not the task-ui-02
  placeholder text.
- `style.css` - `.log-entry`/`.log-time`/`.log-src`/`.log-msg` plus a
  legend, with `warn`/`error` levels visually distinct from `info`/
  `active` (color + background), and `overflow-wrap: anywhere` on
  `.log-msg` so long messages wrap instead of breaking the panel layout.
- `status_console.py` - `system_event_payload()` (pure) and
  `StatusConsoleWindow.push_system_event()`.
- `status_console_ui/demo.html`/`demo.js` - buttons for each `EventLevel`
  plus a "+50 events" stress button, used to verify newest-first ordering,
  the 200-entry cap, and long-message wrapping live in a browser (Preview
  tools) before touching pywebview at all.
- `manual_check_status_console.py` - extended to build a real `EventBus`,
  subscribe `SystemEvent -> console.push_system_event`, and publish sample
  events through the real `publish_system_event()` (same function
  `main.py` calls) every 2 s alongside the existing `RuntimeState` cycle.

**Deliberately not done:** wiring a live `StatusConsoleWindow` into
`main.py`'s `App`/`run()`. `pywebview`'s `webview.start()` runs its own GUI
loop (typically main-thread) alongside this process's asyncio loop - and
reconciling the two is a separate, larger concurrency question than this
card's scope, not yet assigned to any task card. Publishing `SystemEvent` on
`app.bus` is safe regardless (`bus.py`: zero subscribers is a no-op), so
`main.py`'s new calls are real and already correct for whenever that wiring
task happens.

## Acceptance Criteria

- [x] Events are fed through structured logging/events, not console
      scraping. `publish_system_event()` is the only path; nothing parses
      log text.
- [x] Warnings/errors are visually distinct without overwhelming normal
      state. `warn`/`error` get amber/red source badges and message color;
      `info`/`active` stay neutral/cyan.
- [x] Warmup success/failure is visible. `warm_up()` publishes an
      `INFO`/`WARN` `SystemEvent` (source `WARMUP`) on both paths.
- [x] Think on/off and mic sleep/wake remain log-visible - unchanged - and
      are now also `SystemEvent`-visible (source `HOTKEY`).
- [x] Event panel handles long messages without layout breakage.
      `overflow-wrap: anywhere` verified live via the Preview tools at both
      desktop and 360px widths with a 150+ character message - no
      horizontal overflow.

## Test Boundary

`tests/test_system_log.py` (5 tests) and additions to `tests/test_main.py`
(4 tests: mic-sleep/thinking-toggle `SystemEvent` publication, warm-up
success/failure `SystemEvent` publication) and `tests/test_status_console.py`
(5 tests: payload shape, `push_system_event`, static-file structural checks)
cover the pure-logic surface - 208 tests pass project-wide. The real events
panel rendering (colors, wrapping, ordering, the 200-entry cap) was verified
live in a browser via the Preview tools against `demo.html`, not just
asserted structurally in Python.
