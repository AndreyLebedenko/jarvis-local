# Task v1.6.1-1: Builtin provider core

**Status:** Planned.
**Story:** `tasks/story-v1.6.1-builtin-tools-delegated-control.md`
**Depends on:** nothing; first card of the story.

## Summary

Introduce the builtin tool provider concept: registered tools whose
dispatch is an in-process call, flowing through the existing single
interception point with full audit parity, visible in the Control
Center tool list, independent of the MCP module switch.

## Context you need

- `src/jarvis/tools/registry.py`: `ToolRegistry` / `RegisteredTool` -
  the shared namespace builtin tools join (provider collision rules,
  per-tool enable).
- `src/jarvis/tools/interception.py`: `ToolDispatcher` and its
  `_CallableClient` protocol (`call_tool(name, arguments) ->
  ToolCallResult`) - the seam an in-process provider must satisfy;
  note `SOURCE = "MCP"` and the MCP-specific wording in events, which
  must not misattribute builtin calls.
- `src/jarvis/tools/host.py`: `McpHost` currently owns the registry,
  the dispatcher, and the admission gate. "Off equals the capability
  does not exist" refers to MCP client objects/subprocesses - builtin
  tools must stay available with MCP off, and MCP enable/disable must
  not clear builtin registrations (`ToolRegistry.clear()` in
  `disable()` currently would).
- `src/jarvis/dialog/tool_presentation.py` and `src/jarvis/app.py`
  (`build_app`): how the model-facing tool list and dispatch are wired.
- Control Center tool list: how registry contents reach the UI, so
  builtin tools appear there with a distinct provider identity.
- Story design decisions: always-on availability, per-tool toggle,
  `data_boundary = local` always.

## Boundary

- Provider mechanism only, plus a trivial internal test tool if needed
  for wiring tests. `set_reasoning_level` is task 2; memory writes are
  task 3.
- Do not redesign the MCP lifecycle: extract or share ownership of
  registry/dispatcher only as far as the story's stop condition allows.
- No new UI components; the existing tool list rendering may need a
  provider label, nothing more.

## Requirements

- A builtin provider registers `RegisteredTool`s (name, description,
  schema, `data_boundary = local`) under a reserved provider name that
  no MCP server config can claim; a config that tries is rejected with
  a clear error.
- Dispatch of a builtin tool goes through `ToolDispatcher.dispatch()`
  and produces `ToolCallStarted`/`ToolCallFinished` plus the correlated
  `SystemEvent`, with source/wording that does not claim the call was
  MCP traffic.
- Builtin availability is independent of the MCP module switch in both
  directions: MCP off leaves builtin tools callable; MCP
  enable/disable/degraded transitions never drop or duplicate builtin
  registrations.
- The MCP admission gate must not reject builtin calls when MCP is
  off; whatever gate applies to builtin dispatch is defined and tested
  explicitly (including during shutdown).
- Per-tool enable/disable from the Control Center works for builtin
  tools through the existing `set_tool_enabled` path.
- Builtin tool errors surface as normal tool-result errors to the
  model; an unexpected exception inside a builtin tool must not crash
  the turn.

## Acceptance criteria

- [ ] Tests cover: registration under the reserved provider name,
      dispatch through the interception point with correct audit
      events and `data_boundary = local`, MCP off/on/off transitions
      leaving builtin tools intact, per-tool disable blocking dispatch,
      collision between a builtin name and an MCP tool name resolving
      per the registry's existing rejection rules, and an exception
      inside a builtin tool returning a failed `ToolDispatchResult`.
- [ ] `python -m pytest` and Ruff checks are green.
