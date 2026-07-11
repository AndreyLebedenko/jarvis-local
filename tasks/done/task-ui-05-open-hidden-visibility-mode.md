# Task UI-05: Open / Hidden visibility mode

**Story:** story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** средний
**Зависимости:** [task-ui-01-state-and-event-contract.md](done/task-ui-01-state-and-event-contract.md),
[task-ui-04-think-and-reset-controls.md](done/task-ui-04-think-and-reset-controls.md)
(reuses task-ui-04's `js_api`/`run_coroutine_threadsafe` bridge pattern)

## Summary

Implement the system visibility mode as a first-class UI and engine state.

## Scope

- `Open`: normal visibility. Voice output and screen preview follow current
  configuration.
- `Hidden`: reduced external visibility. TTS muted/text-only, screen previews
  hidden by default, sensitive snippets not shown on compact surfaces.
- Visibility mode is independent from data locality.
- Color semantics: Open uses cyan/teal; Hidden uses muted violet/slate; amber
  remains warning/cloud/warmup-adjacent.

## Open Question (resolved before implementation)

Should Hidden change only UI output, or should it also suppress spoken TTS from
ordinary voice turns? This decision affects runtime behavior and must be made
before implementation.

**Resolved (human decision):** Hidden changes only UI output. It does not
touch `audio_in.py`/`tts.py`/`Orchestrator` in any way - ordinary voice turns
speak normally regardless of Open/Hidden. This also resolves the story's own
related open question ("does `Hidden` mute TTS globally or only for
UI-triggered turns?") the same way: neither, because it never touches TTS.
`task-ui-privacy-and-touchstrip-requirements.md`'s Decisions section
("TTS muted/text-only") predates this decision and has been corrected to
match. Scope's "TTS muted/text-only" line above and the AC below about TTS
being "explicitly tested or manually handed off if it touches audio output"
are consequently moot - Hidden does not touch audio output at all in v1, so
there is nothing there to test.

## Implementation

- `visibility_mode.py` - `VisibilityModeState`/`VisibilityModeChanged`,
  shaped like `thinking_mode.py`'s state owner (bus-publishing, starts at a
  default - `VisibilityMode.OPEN`) but with `set_mode(mode)` (a two-target
  setter, not a binary `toggle()`) and no hotkey listener (Scope only asks
  for a UI-level control). `set_mode()` is a no-op (no publish) when given
  the mode that is already active - a real, expected UI input (clicking
  "Open" while already Open), not a bug to guard against elsewhere.
- `status_console.py` - `visibility_mode_payload()`, `StatusConsoleWindow.
  push_visibility_mode()`, and `StatusConsoleApi.set_visibility_mode
  (mode_value)` (same `js_api`/`run_coroutine_threadsafe` pattern as
  task-ui-04's `toggle_thinking()`/`reset_context()`). Publishes an `INFO`
  `SystemEvent` only when the mode actually changed, mirroring
  `VisibilityModeState`'s own redundant-call no-op so the two layers can
  never disagree about what counts as "changed" (same reasoning
  system_log.py's Stop-Condition resolution used in task-ui-03).
- `status_console_ui/index.html`/`demo.html` - a two-button `Open`/`Hidden`
  toggle in the topbar, grouped with (but visually distinct in color, text,
  and a `.topbar-right` wrapper from) the data-locality badge.
  `style.css`'s `.visibility-toggle button.sel[data-mode="hidden"]` uses
  `--violet` (matching the Think switch's "on" color), never `--amber`.
- `status_console_ui/app.js` - `applyVisibilityMode()` sets `data-
  visibility` on `<html>`, updates the toggle's selected button, and calls
  `_renderVisionChipMeta()` - the one concrete Hidden behavior implemented:
  the vision/screen chip's detail text becomes a generic placeholder
  ("превью скрыто (Hidden)") while Hidden is active, remembering the last
  real value (`_lastVisionDetail`) so switching back to Open restores it
  without needing another push from Python. `applyVisibilityMode()`
  deliberately never references `#localityBadge`/`applyDataLocality()` -
  verified both by a test that parses the function body and live via the
  Preview tools (toggling Hidden/Open, locality badge unchanged).
  `setVisibilityMode()` (JS -> Python) is guarded like `toggleThinking()`/
  `requestModuleReset()` - a no-op outside a real `pywebview` window.
  `demo.html`/`demo.js` gained direct-call demo buttons ("visibility:
  open/hidden", "set vision detail") for the same reason task-ui-04's demo
  gained "think switch: on/off" - there is no live backend in a plain
  browser to call back through the real click handler.
- `manual_check_status_console.py` - now also builds a real
  `VisibilityModeState`, wires it into `StatusConsoleApi`, pushes a fake
  vision-chip detail so a human can click Hidden in the real window and see
  it replaced, and bundles the growing set of demo-cycle objects into a
  small `DemoContext` dataclass rather than an ever-longer parameter list.

**Review fix (P1):** the first version subscribed `SystemEvent` and
`ThinkingModeToggled` but never `VisibilityModeChanged` -
`_on_visibility_mode_changed -> console.push_visibility_mode()` was
missing. `StatusConsoleApi.set_visibility_mode()` still updated
`VisibilityModeState` and published the `SystemEvent` correctly, but
nothing ever called `push_visibility_mode()` back, so in the real
pywebview window a click would have logged an event while leaving the
toggle button and vision-chip text unchanged - the manual handoff would
not have actually demonstrated the round trip it claimed to. Fixed by
adding the missing subscription. `tests/test_manual_check_status_console.py`
now exercises `_run_demo_cycle_async()`'s wiring directly with a fake
console (no real window needed): publishes `VisibilityModeChanged`/
`ThinkingModeToggled` on the bus and asserts the matching `push_*()` call
happened, so a future missing subscription in this file fails a fast
automated test instead of only being caught by a human clicking through
`manual_check_status_console.py` by hand.

## Acceptance Criteria

- [x] UI labels use `Open` / `Hidden`, not `Приватно` / `На людях`.
      Verified: static-content test asserts the old labels are absent and
      the new ones are present in `index.html`.
- [x] Hidden does not imply cloud/offline status. Structurally guaranteed
      (see Implementation above) and verified live: toggling Hidden/Open
      never changes `#localityBadge`'s `data-locality`.
- [x] Hidden behavior is visible in module chips and system events. Module
      chips: the vision chip's detail text changes. System events: every
      real mode change publishes an `INFO` `SystemEvent`
      ("Режим Hidden активирован.../Режим Open восстановлен").
- [x] TTS behavior in Hidden is explicitly tested or manually handed off if
      it touches audio output. Moot per the resolved Open Question above -
      Hidden does not touch audio output, so nothing here needs testing or
      a hardware handoff.
- [x] Screen preview hiding is default-safe. There is no live screen-
      preview *image* surface anywhere in the Status Console yet (only the
      vision module chip's text detail) - that text is hidden whenever
      Hidden is active, with no code path that could show the real value
      while Hidden is on (`_renderVisionChipMeta()` is the only place that
      reads `_lastVisionDetail` into the DOM, and it always checks the
      current visibility mode first).

## Test Boundary

`tests/test_visibility_mode.py` (4 tests: default state, real mode change
publishes, redundant same-mode call does not, back-and-forth publishes only
real changes), additions to `tests/test_status_console.py` (7 tests: payload
shape, `push_visibility_mode`, `StatusConsoleApi.set_visibility_mode`
behavior including the redundant-call case, and static-content/structural
checks for the labels, the locality-badge independence, and the violet-not-
amber color rule), and `tests/test_manual_check_status_console.py` (2 tests,
added for the review's P1 fix: `_run_demo_cycle_async()`'s bus wiring for
both `VisibilityModeChanged` and `ThinkingModeToggled` actually calls the
matching `push_*()` back into a fake console). 235 tests pass project-wide.
The toggle/vision-chip-
hiding visuals and the real-click round trip (including the browser-cache
gotcha this task ran into while verifying demo.html - a stale cached
demo.js masked the new buttons until the preview server was restarted) were
verified live via the Preview tools, not just asserted structurally in
Python.

**Human manual verification (real pywebview/WebView2 window):** confirmed -
Open/Hidden toggle switches visually, locality badge unaffected, vision chip
detail hidden/restored correctly, system events appear once per real change
(not on redundant clicks), and task-ui-04's Think toggle/reset buttons still
work. One unrelated finding from this run: `manual_check_status_console.py`
does not respond to Ctrl+C (had to be killed via Task Manager) - documented
in the script's own docstring as a `webview.start()`/native-GUI-loop
limitation (the embedded WebView2 message loop via pythonnet never hands
control back to the Python interpreter, so `SIGINT` is never checked), not a
bug introduced by this task. Not fixed here; close the window instead of
using Ctrl+C.
