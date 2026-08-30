# Story: Status Console UI/UX maturity - interaction, keyboard, TTS toggle

**Status:** Completed 2026-08-11. All task cards done: 1 (interaction
foundation), 2 (context menus), 3 (TTS toggle), 4 (visual pass - objective
fixes), 5 (visual pass - subjective restyle, split from 4 on its close).
**Release:** post-v1.8.0 polish; version to be assigned by the owner. No
major architectural output (the roadmap's one-major-decision-per-release
rule is not triggered): this is an interaction-quality pass plus one small
user-facing control (a TTS on/off toggle).
**Created:** 2026-08-09 (owner request: "improve UI/UX").
**Not in roadmap:** `tasks/done/roadmap-v1.5.1-v1.8.0.md` ends the planned arc at
v1.8.0; this story is post-feature refinement, opened directly from an
owner request, not a roadmap item.

## User-facing goal

Two things the owner asked for, in one story:

1. A more mature, scenario-centric Status Console: usable from the
   keyboard where a user actually operates it (the Journal view and the
   toggle groups), with standard interaction affordances - arrow-key
   navigation, Tab order, Space to select, Enter to activate, F2 to edit
   what is editable, and a right-mouse-button context menu offering the
   relevant actions per item.
2. A way to turn Jarvis's speech (TTS) on and off - a live toggle in the
   dashboard and a default-mode option in config.

## Framing and scope decisions (owner dialog, 2026-08-09)

- Jarvis is primarily a voice assistant; the dashboard is a secondary,
  mostly-watched surface. Keyboard/interaction investment is therefore
  focused where a user really operates by hand - the **Journal** view and
  the three toggle groups - not spread evenly across every chip. The
  Status view stays a simple indicator; no roving navigation over its
  module chips in this story.
- The Status Console is a thin client (`VISION.md`, roadmap cross-cutting
  rule 10). Interaction work (task 1, task 2) is front-end only
  (`status_console_ui/*.js`, `*.css`, `strings.js`); it adds no control
  commands and no engine or transport changes, and is verifiable in the
  browser preview via the existing `demo.html`/`demo.js` harness without
  hardware.
- **F2 maps only to already-editable items** (annotations, memory files,
  transcripts). Journal session titles remain *derived*
  (`_journal_session_title`), not stored; editable session names are a
  separate feature and are out of scope here.
- **Context-menu actions are drawn only from commands/endpoints that
  already exist** - no new engine capability enters through a menu.
- **TTS toggle is UI/config only, never delegable to the model** (roadmap
  cross-cutting rule 9 forbids delegating output-privacy-adjacent
  controls; TTS is output, not a sensor, so a plain runtime toggle is
  acceptable, but it stays off the model's allowlist).
- **Command palette (bound to `Ctrl+Q`, "quick menu") is deferred** out of
  this story. The binding is recorded now so a later palette does not
  re-litigate it. `Ctrl+Q` is free in the WebView window (there is no quit
  hotkey; shutdown is a separate confirm flow).

## Findings from the live interface (owner screenshots, 2026-08-09)

Reviewing the running app (Status, Journal, Settings, wide desktop
layout) confirmed the plan and surfaced concrete, defensible issues that
sharpen the tasks below - especially the previously-vague visual pass:

- **Status**: every module chip shows a reset `↺` button, but
  `reset_module` only publishes a "not implemented" `SystemEvent` - six
  repeated affordances whose sole effect is to log "unsupported"
  (honesty debt). The "Локальные инструменты" list mixes human labels
  ("Доступ к камере", "Запись в память") with raw identifiers
  (`read_history`, `read_history_ranges`). Native form controls
  (checkboxes, and the Settings `<select>`s) render with OS light
  styling, breaking the dark theme. The selected reasoning-level chip is
  purple while the whole rest of the system accents in cyan.
- **Journal**: the four sidebar buttons sit above the session list
  (confirmed target of the task-1 reorg). Session cards weight the green
  monospace timestamp over the title, inverting identity; most sessions
  are near-empty "New context" entries (the derived-title limitation
  already recorded - session titles stay derived this story). The
  drag-drop target strip is always visible in the input dock.
- **Settings**: the TTS section is a wall of raw per-language fields
  (11 on Piper plus Silero) - the natural home for task 3's master TTS
  on/off switch at the top of the section, gating this block.

## Task sequence

Dependency-ordered; task 1 is the foundation task 2 builds on. Task 4
(visual pass) is design-first and may run after 1-3 or in parallel from
its mockup-approval gate.

1. **Interaction foundation** (`tasks/task-ui-ux-1-interaction-foundation.md`)
   - front-end only. Focus design-system (`:focus-visible` ring via
   existing CSS variables, skip-to-content), a single keymap module
   (view switching, `/` -> Journal search, `Esc` -> close menu/panel/
   confirm, `?` -> shortcuts overlay), and two reusable interaction
   helpers: a `radiogroup` (view/visibility/reasoning toggle groups) and a
   `listbox`/roving-tabindex (Journal sessions, tool rows, memory files,
   annotations) with arrows/Home/End/Space/Enter/typeahead and ARIA roles.
   F2 wired only to already-editable items. Also reorganizes the Journal
   sidebar: the primary "+ Новый контекст" action stays with the session
   list; the Память/Аннотации/Консолидация panel-togglers move to a
   `role="toolbar"` in the feed pane header, where those panels actually
   open. No new engine features.

2. **Context menus** (`tasks/task-ui-ux-2-context-menus.md`) - one reusable
   menu component reachable by right-click, `Shift+F10`, and a visible
   menu button, offering per-item actions that already exist as
   commands/endpoints (session: Continue/Delete/Copy title; feed message:
   Copy/Generate transcript/Generate annotation; tool row: Enable/Disable/
   Copy name). Front-end only.

3. **TTS enable/disable** (`tasks/task-ui-ux-3-tts-toggle.md`) - the only
   task with engine + config + transport changes. A single runtime state
   owner (`TtsMuteState`) publishing a bus event; mute-gating in
   `TtsOutput.on_token`/`on_response_complete` with `cancel()` on
   disable; a `set_tts_enabled` control command; a toggle and honest
   status indication on Status (muted vs off-by-failure vs speaking via the
   module-health mechanism); and a `[tts].enabled` config default plumbed
   through `UiConfigSelection`/`write_ui_config`, restart-to-apply.

   Settled sub-decisions (owner, 2026-08-09):
   - Mute silences **speech only**; sound cues still play (they are the
     user's feedback that Jarvis heard/finished).
   - The runtime mute is **not** self-persisting; the default lives
     separately in config, mirroring how visibility mode is runtime-only
     while its analogues persist explicitly. Startup reads `[tts].enabled`
     as the initial runtime value.
   - The config default-mode control renders as a master on/off switch at
     the **top** of the Settings "Синтез речи (TTS)" section, gating the
     existing per-language voice block beneath it (which today is a wall
     of raw fields with no on/off).

4. **Visual language pass, objective fixes** (`tasks/task-ui-ux-4-visual-
   pass.md`, done) - front-end only. Dead `↺` reset affordances hidden
   (wiring untouched), OS-light native form controls (checkboxes, selects)
   themed dark, inconsistent local-tool labels fixed (human label primary,
   identifier secondary/dimmed).
5. **Visual language pass, subjective restyle**
   (`tasks/task-ui-ux-5-visual-restyle.md`, done) - front-end only.
   Monospace scope, an accent-emphasis scale reconciling the lone purple
   reasoning chip, an icon set, session-card weight. Split out of task 4 on
   its close: the mockup gating this work was produced and approved by the
   owner (2026-08-11) as part of task 4, and this card implements exactly
   that approved design.

## Boundary (whole story)

- No command palette, no roving navigation over Status chips, no editable
  session titles.
- Tasks 1-2 add no control commands, no transport changes, no engine
  changes; if a menu action needs a capability that does not already
  exist, that action is dropped, not built.
- Task 3 keeps TTS off the model-delegable allowlist and does not change
  the verified Ollama media transport or the TTS routing/engine contracts.
- No change to Hidden-mode semantics or the runtime-locality contract.

## Verification approach

- Tasks 1-2: browser-preview verification via `demo.html`/`demo.js`
  (keyboard traversal, focus visibility, ARIA roles, menu behavior);
  captured as a manual/preview handoff. No hardware.
- Task 3: pure automated tests for the mute-gating in `TtsOutput`, the
  `[tts].enabled` config parse/write round trip, and the `set_tts_enabled`
  control validation. Live speaker on/off is a human hardware handoff per
  the testing protocol.
