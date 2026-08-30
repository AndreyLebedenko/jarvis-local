# Task v1.9.0-3b: Status-tab live mode toggle, Settings dropdown becomes restart-to-apply default

**Status:** Completed. Automated gates green (`python -m pytest` 2294
passed / 1 skipped, `ruff check`, `ruff format --check`). Codex review
(deep mode): 1 blocking finding (P2 omitted-response-mode-coerced-to-text,
see below), fixed and re-reviewed - second pass: LGTM, no actionable
correctness issues. Human-run handoff verified by the owner 2026-08-30
(all four steps behave as specified).
**Story:** `tasks/story-v1.9.0-response-modes.md` (new scope item, inserted between
tasks 3 and 4 - see story update in this same change).
**Depends on:** task-v1.9.0-2 (hotkey + `ResponseModeState` + the
`set_response_mode` control message + `config.ui.toml` round-trip - all reused,
none re-created).

## Summary

Split "response mode" into two genuinely different things that task 2
deliberately kept as one: a **persisted default for the next launch**
(Settings tab) and a **live toggle for the running session** (Status tab,
new). Today both the hotkey and the Settings drop-down write the same
live+persisted field, which is correct by task 2's own design - but the
owner's playtest of tasks 2-3 found the drop-down's placement misleading: it
sits in `.config-panel` among fields that require "Apply" and a restart, yet
it alone applies immediately with no restart, and it is the only
session-scoped toggle not on the Status tab, breaking the page's own
established grouping (reasoning level, mic, TTS mute, camera privacy all live
there).

## Design decisions (confirmed in discussion, 2026-08-30)

This reverses two things task 2 recorded as deliberate - both discussed and
confirmed with the owner before this card, not a silent substitution:

- **The Settings drop-down stops being live.** It becomes an ordinary
  `UiConfigSelection` batch field like `model`/`microphone`/`ui_language`:
  pending until "Apply", restart-to-apply, no live effect on the running
  session. It represents "the mode a new launch starts in," not "the mode
  right now."
- **A new Status-tab button group is the live toggle**, visually paired with
  `.think-card` (reasoning level), same interaction shape (a
  `role="radiogroup"` of buttons, `sel` class on the active one, driven only
  by the confirmed `ResponseModeChanged` push - never optimistic). It writes
  through the *existing* `set_response_mode` control message /
  `StatusConsoleApi.set_response_mode()` / `ResponseModeState.set_mode(source=
  "UI")` path - the same one the drop-down used to call. No new backend write
  path.
- **`Ctrl+Alt+O` now drives only the live value** (the new buttons), never the
  persisted default. This is *already* `ResponseModeState`'s actual behavior
  today (`cycle_mode()`/`set_mode()` never touch config - see
  `response_mode.py`); what changes is that `app.py`'s
  `_on_response_mode_changed` currently persists on *every* source including
  HOTKEY (line 2408) specifically so "the hotkey and the drop-down both write
  the one persisted field" stays true (its own docstring, `app.py:2392-2400`).
  That symmetry is exactly what this card removes.
- No new config field, no new persisted state, no change to
  `ResponseMode`/`ResponseModeChanged`/`CYCLE_ORDER` semantics. Task 4 (voice)
  is unaffected: it will drive the same live `set_mode(source="VOICE")` path
  the new buttons and the hotkey use.

## Context you need

- [app.py:2390-2416](../src/jarvis/app.py) `_on_response_mode_changed`: drop
  the `update_ui_config_response_mode(...)` call (line 2408) and its
  docstring's persistence rationale. Keep the `publish_system_event(...)`
  log/UI-feedback call - every source (HOTKEY, UI, VOICE) still logs and still
  drives the live push.
- [config.py:1907-1913](../src/jarvis/core/config.py)
  `update_ui_config_response_mode()`: becomes dead code once the call above is
  removed - delete it, and drop the `[response].mode` example from
  `_update_ui_config_scalar_field()`'s docstring (`:1916-1925`; the helper
  itself stays, MCP's `update_ui_config_mcp_enabled()` still uses it).
- [config.py:1815-1897](../src/jarvis/core/config.py) `write_ui_config()`:
  already accepts `response_mode: str | None` (line 1826) and already writes
  `[response] mode` (line 1896) - reuse this parameter as-is, just change what
  value the caller passes (below). No signature change needed here.
- [status_console.py:929-969](../src/jarvis/ui/status_console.py)
  `_save_config_selection_async`: currently passes
  `response_mode=self._response_mode.mode.value` (the *live* value)
  specifically to avoid an unrelated Apply clobbering the live toggle's last
  write (comment at `:965-968`). Once the drop-down carries its own
  selection, pass `response_mode=selection.response_mode` (the form's choice)
  instead - the comment explaining the old bypass no longer applies and
  should go with it.
- [status_console.py:649-663](../src/jarvis/ui/status_console.py)
  `set_response_mode(mode_value)`: keep as-is - this becomes the new
  Status-tab buttons' write path (previously the drop-down's). Its "no second
  write path" comment (`:658-662`) is still true and does not need to change.
- [config_selection.py](../src/jarvis/ui/config_selection.py): add
  `response_mode: str` to `UiConfigSelection` (`:31-45`); extend
  `validate_selection()` (`:48-65`) to validate it via the *existing*
  `validate_response_mode()` (`:68-80`) instead of a second check - reuse,
  don't duplicate. Rewrite `validate_response_mode()`'s docstring: it
  currently says "a live toggle, not a UiConfigSelection batch field"
  (`:69-71`), which becomes wrong; the function itself (the
  `SUPPORTED_RESPONSE_MODES` check) does not need to change, only its framing
  and its second caller.
- [status_console.py:331-364](../src/jarvis/ui/status_console.py)
  `config_values_payload(settings)`: add
  `"response_mode": settings.response.mode` and `"response_mode_options":
  list(SUPPORTED_RESPONSE_MODES)`, matching the existing
  `ui_language`/`ui_language_options` pair exactly. This is the snapshot the
  Settings drop-down now populates from (see below) - the same mechanism
  `uiLangSelect` already uses, not a new one.
- [response_mode.py:1-25](../src/jarvis/dialog/response_mode.py) module
  docstring: rewrite the "Persistence delta from that precedent" paragraph -
  it currently says "the UI (task 2) writes new selections back to
  config.ui.toml"; after this card only the Settings-menu save does, and it
  does so through `write_ui_config`, not through this module at all (this
  module now persists nothing, full stop, same as `ReasoningLevelState`).
  Also re-describe `ResponseModeChanged.source`'s `"UI"` value (`:53-60`): it
  now means "the Status-tab live toggle," not "the drop-down."
- [index.html:108-119](../src/jarvis/ui/status_console_ui/index.html)
  `.think-card`: wrap in a shared row with a new sibling card (see Layout
  below); add the new markup - title (`data-i18n` label, no tag/no status
  subtitle per owner - simpler than `.think-card`), a `role="radiogroup"` of
  3 buttons mirroring `#reasoningLevelToggle` (`:113-118`) structurally, new
  short i18n labels (not the existing `response_mode_*_option` strings, which
  stay on the drop-down and are too long for a button).
- [index.html:173-180](../src/jarvis/ui/status_console_ui/index.html)
  `responseModeSelect`: change `onchange="setResponseMode()"` to
  `onchange="onConfigInputChanged()"`, matching `modelSelect`/`uiLangSelect`'s
  wiring; include it in `applyConfigSelection()`'s payload (`app.js:1053-
  1070`) and populate it from `applyConfigValues()` (`app.js:859-880`) the
  same way `uiLangSelect` is populated (`:861-869`), sourced from the new
  `response_mode`/`response_mode_options` payload fields above.
- [app.js:582-596](../src/jarvis/ui/status_console_ui/app.js) `_responseMode`
  / `applyResponseMode()` / `setResponseMode()`: `applyResponseMode()`
  currently writes into `responseModeSelect.value` (`:589`) - it must stop
  touching the drop-down entirely and instead drive the new button group's
  `sel` class (same shape as `applyThinkingMode()` for
  `#reasoningLevelToggle` - the direct precedent to mirror). Rename
  `setResponseMode()` to take a mode argument and send the live control
  message from a button's `onclick`, mirroring `setReasoningLevel(level)`.
- [style.css:362-389](../src/jarvis/ui/status_console_ui/style.css)
  `.think-card`/`.reasoning-level-toggle`: resize `.think-card` to make room
  for a sibling in the same row (see Layout below); add matching rules for
  the new card, reusing `.reasoning-level-toggle button`'s look for the new
  button group rather than inventing new visual language.
- `status_console_ui/demo.js:283,335` mirrors `config_values_payload()`'s
  shape for the offline demo page - add the two new fields there too or the
  demo page's Settings tab silently diverges from the real one.
- `status_console_ui/strings.js:83-86,394-397` `response_mode_*_option`:
  unchanged, still the drop-down's labels. Add new, shorter en+ru strings for
  the button group (e.g. `mode_text`/`mode_voice`/`mode_text_voice`,
  "Text"/"Voice"/"Text+voice", RU "Текст"/"Голос"/"Текст+голос" - or the
  owner's preferred wording, per the earlier UI/UX discussion).

## Layout

Both cards share one row, matching `.mcp-card`'s `min(760px, 100%)` width
convention already used lower on the same page. `.think-card` and the new
card each get `flex: 1` with a `min-width` (mirroring `.think-body`'s
existing `min-width: 160px` inside `.think-card` for the same purpose) so
they wrap to stacked on a narrow viewport instead of being squeezed -
`.think-card` already uses `flex-wrap` internally for exactly this reason, so
this is the same technique one level up, not a new pattern.

## Boundary

- Only the response-mode UI surfaces and the persistence call site change. No
  change to `ResponseMode`, `ResponseModeChanged`, `CYCLE_ORDER`, or the
  reasoning-level toggle's own behavior.
- No new persisted field and no new config schema - `[response] mode` /
  `Settings.response.mode` keep meaning exactly what they mean today; only
  *who writes it* and *when it takes effect* change.
- Task 4 (voice) is untouched by this card and does not need to change once
  this lands - `source="VOICE"` will drive the same live path the buttons and
  hotkey now use.
- Do not add a "confirm you want to discard the pending Settings selection"
  flow or any other batch-Apply UX beyond what `model`/`microphone`/
  `ui_language` already have - `response_mode` becomes an ordinary field of
  that same form.

## Requirements

- Settings-tab `responseModeSelect` becomes a restart-to-apply field:
  populated from `config_values_payload()`'s new
  `response_mode`/`response_mode_options`, included in
  `applyConfigSelection()`'s `save_config_selection` payload, validated via
  `UiConfigSelection.response_mode`, written by `write_ui_config(...,
  response_mode=selection.response_mode)`. No live effect on selection;
  effect is deferred to next restart, same as `model`.
- A new Status-tab button group (paired visually with `.think-card`, per
  Layout) is the live toggle: three short-labeled buttons, `role=
  "radiogroup"`, selected state driven only by the confirmed
  `ResponseModeChanged` push (never optimistic - same rule as the
  reasoning-level toggle and `applyThinkingMode()`), calling the existing
  `set_response_mode` control message on click.
- `Ctrl+Alt+O` and the new buttons both change only the live value; neither
  persists to `config.ui.toml`. Only a Settings-tab Apply persists.
- `_on_response_mode_changed` no longer persists on any source;
  `update_ui_config_response_mode()` is deleted as dead code.

## Verification

- `python -m pytest`, `ruff check`, `ruff format --check` green.
- Pure tests: `UiConfigSelection`/`validate_selection()` accepts/rejects
  `response_mode` the same way `validate_response_mode()` already does
  standalone; `_save_config_selection_async` writes the form's chosen
  `response_mode` via `write_ui_config`, not the live state's;
  `_on_response_mode_changed` no longer calls any config-write function for
  any source (HOTKEY/UI/VOICE all just log+push); `set_response_mode()`/
  `ResponseModeState.set_mode()` are unaffected (still no persistence inside
  the state class, unchanged from today).
- Human-run handoff (UI/visual + hotkey, per Testing protocol): (1) clicking
  a Status-tab mode button changes the mode immediately, with no
  "restart to apply" banner; (2) `Ctrl+Alt+O` cycles the same live buttons,
  not the Settings drop-down; (3) changing the Settings drop-down and
  clicking Apply shows the pending-restart banner and does NOT change the
  current session's live mode; (4) after a real restart, the app starts in
  whatever mode the drop-down last had Applied, regardless of what the live
  buttons were left on before shutdown. Prepare exact steps; do not run
  these yourself.

## Acceptance criteria

- [x] Status tab shows a live mode toggle next to the reasoning-level card,
      in the same visual language (button group, confirmed-push-only
      selection).
- [x] Settings tab's response-mode control behaves exactly like
      `model`/`microphone`/`ui_language`: pending until Apply,
      restart-to-apply, no live effect.
- [x] `Ctrl+Alt+O` drives the live toggle only; the persisted default changes
      only via a Settings-tab Apply.
- [x] No new persisted field; `ResponseMode`/`ResponseModeChanged`/task 4's
      planned voice path are unaffected.
- [x] Pure tests and `ruff` gates green; the human-run handoff above is
      prepared with exact steps.
- [x] Codex review run (deep mode, 2026-08-30): 1 blocking finding
      (P2 - save_config_selection coerced an omitted response_mode to a
      persisted "text" override, so an unrelated Apply could silently reset
      a previously saved voice/text_voice default). Fixed: the omission
      stays None through to write_ui_config, which omits the [response]
      section - the same optional-field contract as ui_language/vad.
      Regression tests added at the three layers (UiConfigSelection default,
      save_config_selection write path, transport pass-through); full suite
      re-run green.
- [x] Human verifies the handoff above (owner, 2026-08-30: all four steps
      behave as specified).

## Stop Conditions

- If `config_values_payload()` cannot be given the persisted
  `Settings.response.mode` without also exposing the *live* value through the
  same field (i.e. if the two would collide in one payload key), stop - that
  is exactly the ambiguity this card exists to remove, and papering over it
  defeats the point.
- If splitting the write paths turns out to require a second
  `ResponseModeState`-like object (rather than reusing the existing one for
  the live side and `write_ui_config` for the persisted side, as scoped
  above), stop - that would be materially larger than this card's scope.

## Implementation summary (2026-08-30)

- `src/jarvis/ui/config_selection.py`: `UiConfigSelection` gained
  `response_mode: str = "text"`; `validate_selection()` routes it through
  the existing `validate_response_mode()` (no second hardcoded copy).
  `validate_response_mode()`'s docstring rewritten for the split semantics.
- `src/jarvis/app.py` `_on_response_mode_changed`: no longer persists on
  any source; `update_ui_config_response_mode` import removed.
- `src/jarvis/core/config.py`: `update_ui_config_response_mode()` deleted;
  `write_ui_config()`'s `response_mode` parameter and `[response] mode`
  write reused unchanged, docstring reworded to "the Settings form's
  restart-to-apply default"; `_update_ui_config_scalar_field()`'s docstring
  no longer lists `[response].mode`.
- `src/jarvis/ui/status_console.py`: `config_values_payload()` gained
  `response_mode` (from `Settings.response.mode`) +
  `response_mode_options`; `save_config_selection()` gained a
  `response_mode` parameter and passes the form's choice to
  `write_ui_config` (an absent value keeps the built-in "text" default);
  `set_response_mode()` itself is unchanged in behavior - it stays the
  live-toggle write path, comments updated.
- `src/jarvis/ui/transport.py`: `save_config_selection` protocol + `_save_
  config_selection` dispatch carry `response_mode` through a new
  `_parse_response_mode()` shape check (None passes through, mirroring
  `_parse_ui_language`).
- `src/jarvis/dialog/response_mode.py`: module docstring rewritten -
  the task 2 "UI writes back to config.ui.toml" paragraph replaced with
  "this module persists nothing, full stop (task 3b)"; `source="UI"` now
  means the Status-tab toggle.
- Front-end: `index.html` - a new Status-tab `.mode-card` (sibling of
  `.think-card` in a shared `.mode-card-row`) with a
  `role="radiogroup"` of three short-label buttons (`mode_text` /
  `mode_voice` / `mode_text_voice`, en+ru) wired to
  `setResponseMode('<mode>')`; the Settings `responseModeSelect`
  switched to `onchange="onConfigInputChanged()"`, is populated from
  `applyConfigValues()` (same mechanism as `uiLangSelect`), and is
  included in `applyConfigSelection()`'s payload. `applyResponseMode()`
  drives only the new button group's `sel` class (never the drop-down,
  never optimistic). `style.css` places both cards in a wrapping
  `.mode-card-row` (`flex: 1` + `min-width` per card, the same technique
  `.think-body` uses one level down); the button group reuses
  `.reasoning-level-toggle`'s look. `demo.html`/`demo.js` mirror both
  changes. New i18n keys `mode_title`/`mode_text`/`mode_voice`/
  `mode_text_voice` (en+ru).
- No new persisted field; `ResponseMode`/`ResponseModeChanged`/
  `CYCLE_ORDER` untouched; task 4's planned voice path unaffected.

## Verification (performed)

- `python -m pytest` - 2294 passed, 1 skipped.
- `ruff check` - clean. `ruff format --check` - clean.

## Human-run handoff (prepared; do not run in CI, hardware/visual checks)

Hardware/UI-dependent, per the Testing protocol: the agent prepares these
exact steps and stops; the human runs them and reports the outcomes.
State-independent: no step assumes a starting response mode - each says
how to reach the target state from wherever the persistent setting
currently is. Launch command for every step: `python main.py
--status-console` (or your usual entry point). References: hotkey binding
`hotkeys.response_mode_toggle`, default **Ctrl+Alt+O**, `src/jarvis/core/
config.py:140` (`[hotkeys] response_mode_toggle` in config.toml may
override it). Note the README/config.example.toml hotkey documentation
itself remains task-v1.9.0-5's outstanding debt (recorded in
`tasks/bug_reports/2026-08-30-handoff-silently-depends-on-undocumented-hotkey.md`).

1. **Live Status-tab toggle.** In the Status Console's Status tab, find
   the new "Response mode" / "Режим ответа" card next to the "Thinking
   mode" card. Click each of its three buttons in turn
   (Text/Voice/Text+voice). Confirm after each click the button highlights
   immediately, WITHOUT any "restart to apply" banner appearing (compare:
   the Settings tab shows that banner only after its own Apply).

2. **Hotkey drives the buttons, not the drop-down.** Select a mode on the
   Status-tab buttons. Press **Ctrl+Alt+O** (`hotkeys.response_mode_toggle`,
   default `src/jarvis/core/config.py:140`; verifies the live buttons move
   - to the next mode in the cycle text -> voice -> text_voice -> text,
   starting from whatever the buttons currently show). Confirm the button
   group highlights the new mode. Then open the Settings tab: the
   "Response mode" / "Режим ответа" drop-down there has NOT changed (it
   still shows the last value Applied or loaded from `config.ui.toml`/
   `config.toml`).

3. **Settings Apply is restart-to-apply with no live effect.** From an
   arbitrary starting state, open the Settings tab and note the drop-down's
   current selection. Either (a) it already differs from the live button
   selection (common case after step 1-2), or (b) it does not - in that
   case click Apply once with the current selection just to establish a
   known `config.ui.toml`, restart Jarvis, then re-do this step so the
   drop-down now differs from a live mode you can see on the Status tab.
   Now pick a DIFFERENT mode in the drop-down and click "Apply" /
   "Применить". Confirm the amber "restart to apply" banner appears
   ("Changes saved - restart Jarvis to apply." / "Изменения сохранены -
   перезапустите Jarvis, чтобы применить." and a "Settings saved - restart
   Jarvis to apply" event in the events panel). Critically: switch back to
   the Status tab and confirm the live buttons did NOT move - the running
   session's mode is unchanged by the Settings save.

4. **Config persistence: only Apply persists; live toggles do not.** After
   step 3, note what `[response] mode` currently says in `config.ui.toml`
   in the repository root (or that there is no `[response]` section at
   all - that is a valid starting state too). Then cycle the live mode
   with the Status buttons and/or Ctrl+Alt+O to any mode different from
   the Applied value, and confirm `config.ui.toml` is byte-identical
   before and after those live changes (regression check for the Codex
   review finding: a live toggle used to be able to rewrite this file).
   Fully close Jarvis and launch `python main.py --status-console` again.
   Confirm the session starts in the mode the Settings drop-down last had
   Applied (verify on the Status-tab button group's selection), NOT
   whatever the live buttons were left on just before shutdown, and not
   whatever Ctrl+Alt+O cycled to. Then (optional, restores the default):
   set the drop-down back to "Text only" / "Только текст" and Apply - the
   next restart starts in text mode.
