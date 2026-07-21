# Task v1.6.3-2: Content migration

**Status:** Implemented with known gaps; blocked on an owner decision
(see "Known gaps found in review" below) before human visual review.
**Story:** `tasks/story-v1.6.3-status-console-ui-reorg.md`
**Depends on:** task-v1.6.3-1 (tab shell).

**Outcome:** The former inline settings form now lives in the Settings
tab. The old Settings button and the duplicate Status context-reset
button/confirmation were removed. Status keeps live runtime content,
the MCP toggle/tool list, system events, and Shutdown.

## Summary

Move every control to its agreed home: the configuration form to the
Settings tab, Status trimmed to live state and immediate controls,
the duplicate context reset removed, MCP runtime controls separated
from MCP server configuration.

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
- The MCP block: today the toggle, tool list, and (in settings) server
  config are one visual cluster; after this card the toggle + tool
  list live on Status, server configuration fields on Settings. The
  v1.6.1 builtin provider will add tools to the same Status list -
  do not structure the split in a way that assumes tools imply a
  connected MCP server.

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

- Settings tab: model, microphone, UI language, TTS voices, MCP
  server configuration - the complete former inline form, nothing
  left behind on Status.
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

- **MCP server configuration does not exist in the UI.** This card and
  the story both require splitting MCP runtime controls from MCP
  *server configuration*, with the latter moving to Settings. There is
  no server-configuration form anywhere in `index.html` - the inline
  form was only model, microphone, UI language, TTS, and VAD; MCP
  servers are configured in `config.toml`. The requirement as written
  is not implementable by relocation. Per project rule 0.2 this needs
  an owner decision: either drop it from this card's scope explicitly,
  or open it as new UI work in its own card. Until then the first
  acceptance criterion below stays unchecked.
- **`demo.html` is out of sync.** The QA harness lost the Settings and
  Reset buttons but gained neither the tab switcher nor the `.settings`
  wrapper, so the configuration form now renders permanently inside the
  Status column - the harness no longer shows what the product shows.
  This is the same class of drift that task-ui-07 caught as a real bug
  (`PROJECT.md`, demo.html inline-style entry). Fix belongs here.
- **Two changes landed outside this card's boundary** and are moved to
  `tasks/task-v1.6.3-4-status-vertical-density.md`: the window default
  height raised 900 -> 1020, and the console-wide scrollbar theming.
  Both are behavior changes in a card scoped to pure relocation, and
  1020 px does not reliably fit a 1080p display.

## Acceptance criteria

- [ ] Existing automated UI-contract/string tests updated for moved
      and removed controls; no orphaned catalog entries. **Blocked** on
      the MCP server-configuration decision above.
- [ ] `demo.html` renders the same three-tab structure as `index.html`,
      with the configuration form behind the Settings tab.
- [ ] A human-run visual check confirms each tab matches the story
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
