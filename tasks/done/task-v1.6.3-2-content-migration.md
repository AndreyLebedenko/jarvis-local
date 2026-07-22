# Task v1.6.3-2: Content migration

**Status:** Completed. Verified by the human on 2026-07-22 through
the combined v1.6.3 + v1.6.4 checklist in
`tasks/done/task-v1.6.4-3-docs-and-release-verification.md`. The
demo.html sync listed below as an open gap was in fact completed and is
pinned by
`test_demo_html_mirrors_the_tab_structure_it_can_actually_render`; that
status line was stale and was corrected 2026-07-22.

**Defect this card introduced, found by that verification run and
fixed:** moving the configuration form into the `.settings` tab left
`.config-panel`'s `align-self: center` untouched, which silently changed
meaning from horizontal to vertical centering and made the top of the
form unreachable on a short window - see
`tasks/bug_reports/2026-07-22-quiet-microphone-capture-and-unselectable-device.md`.
A pure relocation can still break layout when a declaration's meaning
depends on the parent it was relocated into.
**Story:** `tasks/done/story-v1.6.3-status-console-ui-reorg.md`
**Depends on:** task-v1.6.3-1 (tab shell).

**Outcome:** The former inline settings form now lives in the Settings
tab. The old Settings button and the duplicate Status context-reset
button/confirmation were removed. Status keeps live runtime content,
the MCP toggle/tool list, system events, and Shutdown.

## Summary

Move every control to its agreed home: the configuration form to the
Settings tab, Status trimmed to live state and immediate controls,
the duplicate context reset removed.

## Context you need

- Story design decisions: the full target layout per tab, and the
  runtime-vs-cold-config criterion that resolves any control this
  card finds unassigned.
- `src/jarvis/ui/status_console_ui/app.js` / `index.html`: the
  current console view (avatar, module chips, reasoning selector, MCP
  block, action buttons, inline settings form) and how each control
  is wired to engine-state events - the wiring must move with the
  markup, not be duplicated.
- task-v1.5.3-8 (`tasks/done/task-v1.5.3-8-explicit-new-context-ui.md`):
  why the Journal's "Новый контекст" is the canonical reset; this
  card deletes the console's "Сбросить контекст" without touching the
  underlying command.
- The MCP block: the toggle and tool list are runtime state and live
  on Status. Server configuration has no UI and stays in `config.toml`
  (see the resolved gap below). The v1.6.1 builtin provider will add
  tools to the same Status list - do not structure the block in a way
  that assumes tools imply a connected MCP server.

## Boundary

- Pure relocation plus the two agreed removals (scroll-to-settings
  button, console context reset). No renamed commands, no new
  endpoints, no behavior changes in any moved control.
- Shutdown stays on Status, bottom, visually separated as the single
  destructive action.
- The system events panel stays on Status.
- If any control cannot move without backend/transport changes, stop
  per the story's stop condition.

## Requirements

- Settings tab: model, microphone, UI language, TTS voices, VAD - the
  complete former inline form, nothing left behind on Status. MCP
  server configuration is out of scope, see the resolved gap below.
- Status tab: avatar/state, module chips, reasoning level selector,
  MCP toggle + tool list, events panel, Shutdown. Nothing else.
- Every moved control still reflects engine state live (module
  status, reasoning changes from hotkey/voice, MCP transitions) -
  event subscriptions survive the move.
- Settings edits behave exactly as before (same apply/save semantics,
  same restart implications), only the location changes.
- Removed controls leave no dead code: unused handlers, strings, and
  styles for the deleted buttons are cleaned up in the same change.

## Known gaps found in review (2026-07-21)

- **MCP server configuration does not exist in the UI - resolved,
  dropped from scope (owner decision, 2026-07-21).** This card and the
  story originally required splitting MCP runtime controls from MCP
  *server configuration*, with the latter moving to Settings. There is
  no server-configuration form anywhere in `index.html`: the inline
  form was only model, microphone, UI language, TTS, and VAD, and MCP
  servers are edited in `config.toml` directly. The requirement was not
  implementable by relocation. MCP server configuration stays where it
  is; building a form for it would be new feature work outside a layout
  story. No code change follows from this - only the scope correction
  recorded here and in the story.
- **`demo.html` is out of sync.** The QA harness lost the Settings and
  Reset buttons but gained neither the tab switcher nor the `.settings`
  wrapper, so the configuration form now renders permanently inside the
  Status column - the harness no longer shows what the product shows.
  This is the same class of drift that task-ui-07 caught as a real bug
  (`PROJECT.md`, demo.html inline-style entry). Fix belongs here.
- **Two changes landed outside this card's boundary** and are moved to
  `tasks/done/task-v1.6.3-4-status-vertical-density.md`: the window default
  height raised 900 -> 1020, and the console-wide scrollbar theming.
  Both are behavior changes in a card scoped to pure relocation, and
  1020 px does not reliably fit a 1080p display.

## Acceptance criteria

- [x] Existing automated UI-contract/string tests updated for moved
      and removed controls; no orphaned catalog entries.
- [x] `demo.html` renders the same three-tab structure as `index.html`,
      with the configuration form behind the Settings tab.
- [x] A human-run visual check confirms each tab matches the story
      layout, every moved control works (reasoning change from UI and
      hotkey both render, MCP toggle round-trips, a settings edit
      applies), and the context reset exists only in the Journal.
- [x] `python -m pytest` and Ruff checks are green.

## Human visual review handoff

Run Jarvis normally and open the Status Console. Confirm:

- Status contains runtime state, module chips, reasoning level, MCP
  toggle/tool list, system events, and Shutdown only.
- Settings contains the model, microphone, UI language, TTS, and VAD
  form that previously opened under the Settings button.
- Entering Settings refreshes model and microphone options before Apply
  can be used.
- The old Settings button is gone.
- The old Status context reset is gone; context reset remains available
  only as Journal's New context action on this surface.
- Shutdown still asks for confirmation and stays on Status.
