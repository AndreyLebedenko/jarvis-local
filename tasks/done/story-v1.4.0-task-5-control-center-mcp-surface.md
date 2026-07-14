# Task: Control Center MCP surface

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Completed. Human-reviewed 2026-07-14. Prerequisite task 3 and
the v1.3.0 Control Center are completed.
**Release:** v1.4.0

## Summary

Expose the MCP module in the Control Center: a toggle with truthful state
indication, honest data-source axis behavior for turns that used external
tools, and (nice-to-have) a read-only list of registered tools.

## Current Boundary

- MCP toggle:
  - rides the existing WS `control` channel and layered config write path
    (same pattern as the Think toggle);
  - indication reflects the engine's authoritative module state, not the
    last button press - connecting/degraded states show as such;
  - the toggle is live (task-3 runtime transitions), not restart-to-apply.
- Data-source axis: a turn whose tool calls left the machine is labeled
  distinctly, per the task-2 contract wording; inference locality display
  is unaffected. This is the first real second value on the axis the
  v1.3.0 design kept extensible.
  - The source of truth is `ToolCallStarted.data_boundary`, resolved from
    the server default plus an optional per-tool override. The UI must not
    classify calls from provider names, tool names, arguments, or event
    prose.
  - `local` keeps the turn local-only; `lan` and `internet` identify calls
    that left the machine; `unknown` is rendered as unclassified rather
    than guessed. Multi-call display precedence is
    `internet > lan > unknown > local`.
  - This is declared capability metadata, not packet-monitor evidence.
    Enforcement/observation belongs to the separate egress-watchdog story.
- Tool-call system events (from the interception point) appear in the
  existing events panel, including the outbound-data summary from task 3 -
  the user can see what left the machine and to which provider without a
  new panel or window.
- Nice-to-have, implemented: a read-only list of
  registered tools (name, provider, enabled/available) rendered
  data-driven from the registry snapshot - same pattern as the modules
  panel. No per-tool controls in this release.
- No new transport work; everything rides `state`/`control` channels.

## Acceptance Criteria

- [x] Toggle state always matches engine state, including failure/
      degraded cases (no fake success).
- [x] MCP-off hides or clearly zeroes all MCP presence in the UI; nothing
      suggests the capability exists.
- [x] Data-source axis tests cover: local-only turn, external-tool turn,
      LAN turn, unknown-boundary turn, multi-call precedence, and
      independence from Open/Hidden visibility mode.
- [x] `python -m pytest` passes (854 passed, 1 skipped).
- [x] Manual visual checklist items prepared for task 6's handoff.

## Manual Visual Checklist For Task 6

1. Start with MCP disabled. Confirm the card says `Off`, the tool list is
   empty, inference remains `Local`, and the turn source says local sources.
2. Enable MCP. Confirm `Connecting` appears before the authoritative terminal
   `On` or `Degraded` state; the button must not claim success first.
3. Confirm every registered tool row shows its name, provider, and truthful
   enabled/available state. A failed provider must not leave available tools.
4. Exercise one tool at each configured boundary. Confirm `local` leaves the
   turn local-only, `lan` shows LAN, `internet` shows Internet, and `unknown`
   is explicitly unclassified. For several calls, confirm the widest declared
   boundary wins.
5. Switch Open/Hidden after each source state and confirm the source and
   inference-locality badges do not change.
6. Confirm the existing events panel shows tool start/outcome rows, including
   provider and outbound-data summary, without opening another panel.
7. Kill a provider during a call. Confirm the module becomes `Degraded`, its
   tools disappear or become unavailable, and no healthy state is fabricated.
8. Disable MCP. Confirm `Disconnecting` appears before `Off`, the list clears,
   and a restart preserves the disabled state.

## Stop Conditions

- Stop if truthful state indication is impossible because the engine
  lacks an authoritative signal - fix the signal in task 3, not the UI.
- Stop if the axis labeling conflicts with the task-2 contract wording.
