# Task v1.9.0-2: Cycling hotkey + UI drop-down for response mode

**Status:** Completed. Automated logic tests green (`python -m pytest`,
`ruff check`, `ruff format --check`); human-run hotkey/persistence handoff
prepared for the owner (hardware-dependent, per Testing protocol). Codex
stop-time review: 3 findings (hotkey persistence gap, optimistic `<select>`
update, batch Apply erasing the live mode), all fixed and re-verified.
Merged to `main`.
**Story:** `tasks/story-v1.9.0-response-modes.md` (scope item 2).
**Depends on:** task-v1.9.0-1 (the `ResponseModeState`, `ResponseModeChanged`
event, and the `[response] mode` config field).

## Summary

Two ways to change the response mode, both writing the same persisted field:
a single global hotkey that cycles `text -> voice -> text_voice -> text`
(following the `thinking_toggle` precedent), and a config-page control. Per
owner decision (2026-08-29) the UI control is a `<select>` drop-down, NOT a
`role="radiogroup"` button group like the reasoning-level toggle. Both take
effect for subsequent turns; the mode persists across restarts.

## Context you need

- `src/jarvis/dialog/thinking_mode.py:85` `run_hotkey_listener`: the exact
  hotkey-provider wiring - config-driven binding, injectable provider,
  `run_coroutine_threadsafe(state.cycle_*(source="HOTKEY"), loop)`, decision
  made inside `cycle_*` on the event loop (never read state in the callback
  thread). Mirror this for `ResponseModeState.cycle_mode`.
- `src/jarvis/core/config.py:118` `HotkeySettings`: add the new binding here.
  Taken `ctrl+alt+<letter>`: s, r, q, m, v, t, i. Pick a free letter (candidate:
  `o` for "output mode"). **Stop condition:** if no free `ctrl+alt+<letter>`
  is available without reassigning an existing binding, stop and ask - a
  reassignment is a user-facing breaking change (story stop conditions).
- `src/jarvis/app.py:1432` (`thinking_mode = ReasoningLevelState(bus)`) and
  `:2167` `_on_reasoning_level_changed`: where the state is constructed, its
  hotkey listener spawned, and its change event handled/pushed to the UI.
  Wire `ResponseModeState` and its listener the same way; add an
  `_on_response_mode_changed` that pushes the new mode to the status console.
- `src/jarvis/ui/config_selection.py`: the shared validation module for the
  config payload (`UiConfigSelection` + `validate_selection`). Add the mode
  field here so both the command handler and `StatusConsoleApi` validate it
  (the "defense on both sides" rule). Reuse the enum's valid values from
  task 1; do not hardcode a second copy of the string list beyond the JS
  mirror.
- `src/jarvis/ui/status_console_ui/index.html`: the config panel with the
  existing `<select id="modelSelect">` / `micSelect` / `uiLangSelect`. Add a
  `<select id="responseModeSelect">` in the same style. The reasoning-level
  `role="radiogroup"` at `:113` is the anti-pattern here - do NOT copy it.
- `src/jarvis/ui/status_console_ui/app.js`: `applyThinkingMode` (`:539`) and
  `setReasoningLevel` (`:551`) show the "server is the source of truth, DOM
  never optimistically updates" rule. The mode `<select>` follows the same
  rule: its value only changes when a `ResponseModeChanged` push arrives, and
  changing it sends a control message. `strings.js` for i18n labels of the
  three modes (en + ru).
- `config.ui.toml`: the write-back target (like `tts.enabled` / `ui.language`).
  Saving from the config menu persists the mode here; startup layering already
  merges `config.ui.toml` over `config.toml` (task 1's field reads the merged
  value). Confirm the mode round-trips through `write_ui_config`.
- CLAUDE.md tooling note 7: the Browser-pane `file://` sub-resource cache when
  verifying `app.js`/`index.html` edits.

## Boundary

- Only the hotkey and the drop-down. No voice trigger (task 4).
- The drop-down and hotkey both write the one persisted field via the existing
  state owner; no second write path, no per-turn override.
- No new modes, no change to mode semantics from task 1.
- No change to the reasoning-level toggle, mic-sleep, or interrupt hotkeys.

## Requirements

- New `HotkeySettings` binding (free `ctrl+alt+<letter>`, or stop) and a
  `run_hotkey_listener` for `ResponseModeState.cycle_mode`, spawned in
  `app.py` alongside the reasoning-level listener.
- A `<select>` response-mode control in the config panel, labeled per mode
  (three options), i18n-backed, following the config-select style. It reflects
  the server-pushed mode and, on change, sends a control message that routes
  through `ResponseModeState.set_mode(source=...)` and persists to
  `config.ui.toml`.
- `_on_response_mode_changed` handler that pushes the current mode to the UI
  so hotkey changes and UI changes both keep the drop-down in sync (single
  source of truth, same as reasoning level).
- Validation of the mode value in `config_selection.py` (both sides) with the
  JS mirror in the front-end.

## Verification

- `python -m pytest`, `ruff check`, `ruff format --check` green.
- Pure tests: config-selection validation of the mode field (valid + reject
  unknown); the command/`StatusConsoleApi` path routing a UI change through
  `set_mode`; `config.ui.toml` round-trip via `write_ui_config`; the
  changed-event push payload.
- Human-run handoff (hardware/visual, per Testing protocol): (1) the hotkey
  cycles `text -> voice -> text_voice -> text` and the drop-down updates to
  match; (2) selecting a mode in the drop-down persists across a restart;
  (3) both paths take effect on the next turn. Prepare the exact steps and
  commands; do not run these yourself.

## Acceptance criteria

- [x] The single hotkey cycles the three modes; the config drop-down shows and
      sets the same state; both persist to the same field and apply to
      subsequent turns.
- [x] The UI control is a `<select>` drop-down (not a button group) matching
      the existing config selects, with i18n labels for all three modes.
- [x] A UI selection survives a restart (persisted to `config.ui.toml`).
- [x] Pure tests and `ruff` gates green; the human-run hotkey/persistence
      handoff is prepared with exact steps.
