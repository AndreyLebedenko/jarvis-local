# Task UI-06: Touchstrip glance surface

**Story:** story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** средний
**Зависимости:** [task-ui-01-state-and-event-contract.md](done/task-ui-01-state-and-event-contract.md),
[task-ui-05-open-hidden-visibility-mode.md](done/task-ui-05-open-hidden-visibility-mode.md)
(also reuses task-ui-04's `js_api`/`StatusConsoleApi` bridge)

## Summary

Design the narrow touch surface as its own UI, not a compressed desktop
dashboard.

## Scope

- Glance page: runtime state, model/backend label, key module dots, visibility
  mode.
- Actions page: Think toggle and context reset with hold-to-confirm.
- Optional activation trigger through orb/touch affordance after warmup story
  lands.
- No dense event log on touchstrip.

## Stop Condition (evaluated before implementation)

If the chosen GUI framework cannot support this surface without a separate
process or large architecture change, stop and split the touchstrip work into
its own story.

**Evaluated: not triggered.** `pywebview` supports creating multiple windows
in one process (`webview.create_window()` can be called more than once
before a single `webview.start()`), so the touchstrip is a second
`StatusConsoleWindow` subclass in the same process, not a new process or
architecture.

## Implementation

- `status_console_ui/contract.js` (new) - `RUNTIME_STATES`/`MODULE_IDS`/
  `HEALTH_STATUSES`/`EVENT_LEVELS`/`VISIBILITY_MODES`, extracted out of
  `app.js` and loaded before both `app.js` and `touchstrip.js` - the AC
  "Same state contract as desktop Status Console is reused" is now
  structurally enforced at the JS layer (one array, two consumers), not
  just true by convention. `index.html`/`demo.html` updated to load it.
- `status_console_ui/touchstrip.html`/`touchstrip.css`/`touchstrip.js`
  (new) - a two-page (Glance/Actions) surface sized for a ~900x230 touch
  strip device, its own layout entirely (no reuse of `style.css`'s
  desktop grid). Glance page: orb + runtime state + substatus + combined
  model/locality line + a tappable Open/Hidden badge + four module dots
  (microphone/TTS/memory/vision - backend has no dot, it's the text line
  instead, matching `.planning/UI/mock-ups/jarvis_touchstrip_concept.html`).
  Actions page: Think toggle button and a reset button requiring a 1s
  pointer hold (`RESET_HOLD_MS`, `onResetHoldStart()`/`onResetHoldEnd()`) -
  releasing early cancels cleanly, no partial reset ever fires. No Google
  Fonts/CDN reference, system font stack only, same as the desktop shell.
  No emoji, unlike the mock-up's presence/think icons - kept consistent
  with the desktop shell's existing minimal-glyph style (`⟲` only, already
  used there).
- `touchstrip.js` exposes the exact same `applyRuntimeState()`/
  `applyModuleHealth()`/`applyModelLabel()`/`applyDataLocality()`/
  `applyThinkingMode()`/`applyVisibilityMode()` function names as `app.js`,
  so `status_console.py`'s existing `push_*()` methods work against either
  window's `evaluate_js` bridge without modification - only the DOM they
  update differs.
- `status_console.py` - `StatusConsoleWindow.__init__()` gained
  `title`/`url`/`width`/`height`/`min_size`/`resizable` parameters
  (defaulting to the existing desktop values, so no existing call site or
  test needed to change) and `TouchstripWindow(StatusConsoleWindow)`
  overrides them for `touchstrip.html` at 900x230, non-resizable.
  `TouchstripWindow.push_system_event()` is overridden to raise
  `NotImplementedError` - Scope excludes a dense event log from this
  surface, and `touchstrip.js` has no `appendSystemEvent()` to call, so a
  caller mistake here fails loudly instead of throwing an opaque JS
  `ReferenceError` inside `evaluate_js`.
- Both windows can share one `StatusConsoleApi` instance (`pywebview`
  allows binding the same `js_api` object to more than one window) -
  toggling Think mode or Open/Hidden from either surface is one real
  engine state change, not two independently-tracked copies.
  `manual_check_status_console.py` now opens both windows this way and
  pushes state to both every cycle.
- **Deferred, per Scope's own wording** ("optional... after warmup story
  lands"): the activation trigger through the orb/touch affordance -
  `tasks/backlog/activation-warmup.md` has not landed yet, so there is no
  `trigger_warmup()`/`WARMING`-transition mechanism for this surface to
  hook into.

## Acceptance Criteria

- [x] Touch targets are large enough for finger input. `.act-btn` is
      150px tall; paging dots have a 32x32px hit area (12px padding around
      an 8px dot) - measured live via the Preview tools at the real
      900x230 viewport size, not just asserted in CSS source.
- [x] Text remains legible on a roughly 900 x 230 class surface. Font
      sizes carried over from the human-authored mock-up (22px state,
      11px substatus, 15px action label); verified live that nothing
      overflows or clips at exactly 900x230.
- [x] Reset requires hold or equivalent confirmation. A 1s pointer hold,
      not a tap - verified live (hold-then-release before 1s cancels with
      no API call; a full 1s hold fires `reset_context()`, guarded and
      silently no-op outside a real `pywebview` window during this
      browser-based check).
- [x] Hidden mode suppresses sensitive previews on this surface by
      default. There is no per-module detail text or screen-preview
      surface anywhere on the touchstrip (only colored dots) - "sensitive
      previews" have nothing to show regardless of Open/Hidden, so this
      holds trivially and by construction, not by an added hiding rule
      (same reasoning task-ui-05 used for the desktop's AC before that
      task added the vision-chip-hiding behavior - the touchstrip never
      reached that point in the first place, since Scope only asks for
      dots here).
- [x] Same state contract as desktop Status Console is reused. Structural:
      `touchstrip.js` defines the identical `apply*()` function names as
      `app.js`, and both load the same `contract.js` validation arrays -
      verified by a test that greps both files for the same six function
      signatures.

## Test Boundary

`tests/test_touchstrip.py` (13 tests): `TouchstripWindow`'s
url/size/resizable/`push_system_event`-raises behavior, static-content
checks (no hardcoded model name, no Google Fonts/CDN, no old Open/Hidden
labels, no event-log element/function, hold-not-tap reset logic, the
shared `apply*()` function names, the shared `contract.js` load, and that
`app.js` no longer carries its own copy of the contract arrays). Additions
to `tests/test_manual_check_status_console.py` (existing 2 tests extended
to assert both windows receive the same pushes, since they now share one
`StatusConsoleApi`). 248 tests pass project-wide. Layout/touch-target
sizing, page-switching, the hold-to-confirm timer's cancel-on-early-release
behavior, and the Open/Hidden badge's independence from the model/locality
line were verified live via the Preview tools at the real 900x230 size,
not just asserted structurally in Python. The real touchstrip device
itself (or a window at this size on the human's actual desktop) is
hardware/environment-dependent per CLAUDE.md's testing protocol -
`manual_check_status_console.py` opens both windows for that handoff.
