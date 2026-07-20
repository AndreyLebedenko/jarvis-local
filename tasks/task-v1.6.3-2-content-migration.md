# Task v1.6.3-2: Content migration

**Status:** Planned.
**Story:** `tasks/story-v1.6.3-status-console-ui-reorg.md`
**Depends on:** task-v1.6.3-1 (tab shell).

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

## Acceptance criteria

- [ ] Existing automated UI-contract/string tests updated for moved
      and removed controls; no orphaned catalog entries.
- [ ] A human-run visual check confirms each tab matches the story
      layout, every moved control works (reasoning change from UI and
      hotkey both render, MCP toggle round-trips, a settings edit
      applies), and the context reset exists only in the Journal.
- [ ] `python -m pytest` and Ruff checks are green.
