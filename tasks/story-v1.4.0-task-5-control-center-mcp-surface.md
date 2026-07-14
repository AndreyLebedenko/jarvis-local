# Task: Control Center MCP surface

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Planned. Prerequisite task 3 and the v1.3.0 Control Center are
completed.
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
- Nice-to-have, skipped without ceremony if it slips: a read-only list of
  registered tools (name, provider, enabled/available) rendered
  data-driven from the registry snapshot - same pattern as the modules
  panel. No per-tool controls in this release.
- No new transport work; everything rides `state`/`control` channels.

## Acceptance Criteria

- [ ] Toggle state always matches engine state, including failure/
      degraded cases (no fake success).
- [ ] MCP-off hides or clearly zeroes all MCP presence in the UI; nothing
      suggests the capability exists.
- [ ] Data-source axis tests cover: local-only turn, external-tool turn,
      LAN turn, unknown-boundary turn, multi-call precedence, and
      independence from Open/Hidden visibility mode.
- [ ] `python -m pytest` passes.
- [ ] Manual visual checklist items prepared for task 6's handoff.

## Stop Conditions

- Stop if truthful state indication is impossible because the engine
  lacks an authoritative signal - fix the signal in task 3, not the UI.
- Stop if the axis labeling conflicts with the task-2 contract wording.
