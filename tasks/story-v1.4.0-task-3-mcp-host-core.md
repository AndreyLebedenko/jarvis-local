# Task: MCP host core

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Planned. Blocked by task 1 (spike facts in `PROJECT.md`) and
task 2 (locality contract revision): a configured MCP server subprocess may
itself reach the network, so the revised contract must be in force before
any real server can be configured.
**Release:** v1.4.0

## Summary

Implement the host side of MCP inside the engine: MCP client connections,
a tool registry, the single interception point for all tool calls, and the
switchable module state. No model wiring and no UI in this task.

## Current Boundary

- New package (for example `src/jarvis/tools/`) containing:
  - MCP client management: connect/disconnect to configured MCP servers
    (stdio subprocess transport first; SSE/HTTP later if a concrete server
    needs it), using the official Python MCP SDK - add it to
    `requirements.txt` in the same commit;
  - tool registry: aggregated declarations from connected servers, exposed
    as data (`name`, schema, provider, enabled flag) - the model
    presentation layer (task 4) and the Control Center list (task 5) are
    both views over this registry;
  - the interception point: one dispatch function through which every
    tool call passes - checks module state and per-tool enablement,
    publishes a system event for call and outcome, executes via the owning
    MCP client, returns a typed result. Nothing else in the codebase may
    execute a tool.
- Switchable module state:
  - `[mcp] enabled` in the layered config, default `false`, UI writes the
    UI config layer as usual;
  - disabled means: no server processes spawned, no connections, empty
    registry - equivalent to the capability not existing;
  - runtime toggle transitions cleanly (enable connects, disable
    disconnects and clears), with a system event on each transition.
- MCP servers are registered components in the `VISION.md` sense: config
  declares them (command, args, per-server enabled flag); a failing server
  degrades to an honest error state, never fake health.
- Pure tests with a fake MCP client covering: registry aggregation,
  interception ordering (state check, event, execute, event), disabled
  semantics, and toggle transitions.

## Acceptance Criteria

- [ ] With `[mcp] enabled = false`, no subprocess is spawned and the
      registry is empty (asserted in tests).
- [ ] A config/app-construction-level regression test asserts the disabled
      invariant structurally: no client manager with lazy side effects is
      even constructed, so "off equals the capability does not exist" is
      enforced at build time, not just at call time.
- [ ] Every dispatch path goes through the single interception function;
      no second execution path exists.
- [ ] Call and outcome system events carry tool name, provider, duration,
      and a user-readable summary of the outbound data (what is being sent
      and to which provider) - enough for the events panel, the "where does
      my data go" answer, and later watchdog rules.
- [ ] Registry survives server connect/disconnect with correct contents.
- [ ] `python -m pytest` passes without any real MCP server or network.

## Stop Conditions

- Stop if the MCP SDK forces a lifecycle that cannot live inside the
  engine's asyncio loop.
- Stop if clean disable proves impossible without leaking processes or
  connections.
