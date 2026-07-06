# Task UI-04: Think and reset controls

**Story:** story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** высокий
**Зависимости:** [task-ui-01-state-and-event-contract.md](done/task-ui-01-state-and-event-contract.md),
[task-ui-02-desktop-status-console-shell.md](done/task-ui-02-desktop-status-console-shell.md),
[task-ui-03-system-events-panel.md](done/task-ui-03-system-events-panel.md)

## Summary

Add the minimal controls the first UI needs: Think toggle, context reset and
per-module reset requests.

## Scope

- Think toggle mirrors existing `ThinkingModeState`.
- Global reset is labeled as context/conversation reset and requires
  confirmation.
- Per-module reset controls are explicit: STT/microphone, backend/model, TTS,
  memory, vision/screen.
- Reset actions are engine requests with visible system events.

## Stop Condition (resolved before implementation)

If a module has no lifecycle/reset API, do not fake success in UI. Stop and
record the missing engine capability.

**Triggered:** none of backend, microphone, TTS, memory, or vision has any
lifecycle/reset API today (verified by reading `main.py`/`audio_in.py`/
`tts.py`/`backend.py`/`capture.py` - no `reset()`/`restart()`/`reconnect()`
method exists anywhere).

**Resolved, directly answering the story's own open question** ("should
reset module actions be available before module lifecycle APIs are
formalized, or should they start as log-visible requests only?"): **start as
log-visible requests only.** `StatusConsoleApi.reset_module()` (in
`status_console.py`) always publishes a `WARN`-level `SystemEvent` honestly
stating "no engine reset API exists yet" for the requested module - it never
claims success, and no module gains a fake reset path. This directly
satisfies the AC "Module reset failure is reported in system events": a
reset is genuinely attempted (the JS -> Python round trip is real), and its
current, honest outcome (not supported) is what gets reported.

Two controls *do* have a real, narrowly-scoped engine capability and are
fully wired, not request-only: the Think toggle (`ThinkingModeState.toggle()`
already existed) and the global context reset (`ConversationHistory.clear()`,
a small new method added by this task - genuinely implementable, not blocked
by the Stop Condition, since it is not a "module lifecycle API" gap).

## Implementation

- `main.py` - `ConversationHistory.clear()`: drops every recorded turn.
  Deliberately narrow - does not touch `Orchestrator`'s own busy/pending-
  screenshot state, which is a different concern.
- `status_console.py` - `StatusConsoleApi`, exposed to the front-end as
  `window.pywebview.api` via a new `js_api` parameter on
  `StatusConsoleWindow.create()`. This is the first JS -> Python direction
  of the bridge (task-ui-02/03 only ever pushed Python -> JS via
  `evaluate_js`). Every public method (`toggle_thinking()`,
  `reset_context()`, `reset_module(module_id)`) is a plain sync callable
  that schedules its real async work via `asyncio.run_coroutine_threadsafe()`
  - the same race-avoidance pattern this project's hotkey listeners already
  use, since `pywebview` invokes `js_api` methods from its own GUI thread,
  not the asyncio loop's thread.
  - `loop` is optional at construction and set later via `set_loop()`
    (every method is a no-op before that call): `create_window(js_api=...)`
    needs the object *before* `webview.start()` runs the GUI loop, but the
    real asyncio loop this object needs typically only exists *inside* the
    callback `webview.start()` invokes - a genuine ordering constraint, not
    an oversight. See `manual_check_status_console.py` for the real
    sequence.
  - `reset_context()` calls `ClearableHistory.clear()` (a `Protocol`, not a
    concrete import of `main.ConversationHistory` - keeps `status_console.py`
    from depending on the top-level wiring module) then publishes an `INFO`
    `SystemEvent`.
  - `reset_module()` always publishes the honest `WARN` event described
    above, mapping each `ModuleId` to a `SystemEvent` source
    (`BACKEND`->`LLM`, `MICROPHONE`->`STT`, `TTS`->`TTS`, `MEMORY`->`ENGINE`,
    `VISION`->`CAPTURE`).
- `status_console_ui/index.html`/`app.js`/`style.css` - the Think switch
  (`.think-card`/`.switch`) and reset zone (`.reset-zone`/`.btn-reset-global`/
  `.confirm-row`) replace task-ui-02's disabled placeholders; each chip
  gained a `⟲` reset button (`.chip-reset`). Clicking the switch/reset
  buttons never optimistically updates the DOM - only `applyThinkingMode()`
  (called back from the real event) changes the switch's visual, matching
  the story's "UI consumes engine state through explicit events/snapshots."
  `window.pywebview` is `undefined` outside a real `pywebview` window, so
  every `js_api` call in `app.js` is guarded (`_pywebviewApi()`).
- `status_console_ui/demo.html`/`demo.js` - added "think switch: on/off"
  buttons calling `applyThinkingMode()` directly (there is no live backend
  in a plain browser to call back), and the real confirm/cancel/reset-icon
  buttons already work standalone since showing/hiding the confirm row is
  pure local UI state. Verified live via the Preview tools: switch class/tag
  update correctly, confirm row shows/hides, clicking a chip reset icon
  never throws even with `window.pywebview` undefined, no layout overlap
  between chip meta text and the new reset icon at desktop or 360px widths.
- `manual_check_status_console.py` - now builds a real `ThinkingModeState`/
  `ConversationHistory`/`StatusConsoleApi`, passes `js_api=api` to
  `console.create()`, and calls `api.set_loop()` once the async demo cycle's
  own loop exists - proving the construction-order sequence described above
  end-to-end for a human to click through.

## Acceptance Criteria

- [x] Think toggle preserves existing semantics: sampled at next accepted
      turn, not mid-stream. Unchanged - `StatusConsoleApi.toggle_thinking()`
      calls the exact same `ThinkingModeState.toggle()`
      `Orchestrator._start_turn()` already samples synchronously; no new
      code path was introduced between them.
- [x] UI never displays reasoning text or `message.thinking`. Untouched by
      this task - `backend.py`'s stream loop still never reads
      `message.thinking` (task-ui-01/PROJECT.md's existing isolation rule);
      this task adds no new path that could leak it.
- [x] Global context reset confirms before destructive action.
      `showResetConfirm()`/`hideResetConfirm()` gate `confirmContextReset()`
      - verified live (Preview tools): the confirm row is hidden by default,
      shows on the reset button click, and only the final "Сбросить" click
      calls the API.
- [x] Module reset failure is reported in system events. Every
      `reset_module()` call publishes a `WARN` `SystemEvent` - see Stop
      Condition resolution above. Parametrized test covers all five
      `ModuleId` values.
- [x] Controls have testable pure-logic handlers where possible.
      `StatusConsoleApi`'s methods are tested directly (fake history, real
      `EventBus`/`ThinkingModeState`, the current event loop) with no
      pywebview/WebView2 dependency.

## Test Boundary

`tests/test_status_console.py` gained 13 tests: 8 for `StatusConsoleApi`
(no-op-before-`set_loop`, toggle/reset/module-reset behavior - parametrized
across all 5 `ModuleId` values for the honest-failure reporting), 2 for
`StatusConsoleWindow`'s new `push_thinking_mode()`/`create(js_api=...)`
plumbing, and 3 static-file structural checks (real think switch present, a
reset button per module, confirm-before-reset markup).
`tests/test_main.py` gained 1 test for `ConversationHistory.clear()`. 222
tests pass project-wide. The switch/confirm-row/reset-icon *visuals* were
verified live in a browser via the Preview tools (demo.html), not just
asserted structurally in Python; the real `js_api` round trip
(`window.pywebview.api.*`) is hardware/WebView2-dependent and is
`manual_check_status_console.py`'s job, per CLAUDE.md's testing protocol.
