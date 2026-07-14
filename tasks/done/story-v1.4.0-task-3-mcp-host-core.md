# Task: MCP host core

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Completed. Human-reviewed 2026-07-14. Hardware verification is
not applicable to this pure host-core slice; the automated suite and the
real-SDK adapter seam tests pass without a live server or network.
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

### Architecture decision, recorded after implementation review (2026-07-14)

Implementation surfaced a real tension in the boundary above and was
revised with explicit human sign-off; see `PROJECT.md`'s MCP host core
section for the full write-up. Summary:

- **Persistent controller, not conditional construction.** `McpHost` is
  always constructed by `build_app()` regardless of `[mcp].enabled` -
  originally the intent was to omit it entirely when off, but that leaves
  nothing for a later live toggle (task 5's Control Center switch) to
  call `enable()` on. `McpHost` genuinely is a client manager (it owns
  `_client_factory`, `_clients`, and the connect/disconnect loop); the
  "off equals the capability does not exist" guarantee instead rests on
  it holding no client objects and spawning no subprocess at rest
  (status `OFF`) - `client_factory` is invoked only from inside
  `enable()`.
- **A five-state status model**, not a bare bool: `OFF` / `CONNECTING` /
  `ON` / `DEGRADED` / `DISCONNECTING`, with `McpModuleStatusChanged`
  published on every transition as the typed, authoritative signal task
  5 needs (a generic `SystemEvent` alone is not fine-grained or
  guaranteed-ordered enough). `DEGRADED` covers partial connect failure,
  a rejected tool-name collision, and a previously-healthy provider whose
  `call_tool()` raised (transport/session failure, distinguished from a
  tool merely reporting `isError`).
- **An admission gate**, not a plain enabled/disabled bool read by
  `dispatch()`: `disable()` closes admission synchronously before its
  first `await`, then waits for any already-admitted call to drain before
  touching a client, so a concurrent `dispatch()` can never acquire a
  client reference mid-teardown. Status-event ordering matches this
  exactly - `enable()` opens admission before publishing `ON`/`DEGRADED`;
  `disable()` closes admission and publishes `DISCONNECTING` before
  awaiting the drain - so a subscriber reacting to the status event the
  instant it fires always sees `dispatch()` behave consistently with what
  that status claims.
- **Tool-name collision policy: reject, not last-write-wins.** A later
  provider's tool that collides by name with an already-registered
  different provider's tool is rejected outright (the earlier
  registration is kept); the rejecting server is marked `DEGRADED`, not
  disconnected.
- All `ui_message` text goes through `jarvis.ui.text`'s catalog
  (`ui_language` threaded from `settings.ui.language` into `McpHost`/
  `ToolDispatcher`), per the existing localization contract - no hardcoded
  Russian or English prose in `jarvis/tools/`.
- **One stdio connection-owner task**, because the official SDK's AnyIO
  task-group cancel scope must exit in the same asyncio task that entered
  it. `StdioMcpClient.connect()` starts and awaits readiness from that
  owner; `disconnect()` signals and awaits it. Startup and future Control
  Center toggles may therefore originate in different tasks without
  moving SDK context exit across a task boundary.
- Cancellation after `ToolCallStarted` completes exactly one correlated
  outcome before propagating. Cancellation during server discovery
  disconnects the not-yet-registered client and rolls the host back to
  its inert `OFF` state.

## Acceptance Criteria

- [x] With `[mcp] enabled = false`, `McpHost` is constructed (see the
      Architecture decision above) but holds no client objects and never
      invokes `client_factory` - status stays `OFF`, registry stays
      empty, no subprocess is spawned (asserted in tests).
- [x] A config/app-construction-level regression test asserts this
      structurally: `McpHost` exists but is provably inert (`status ==
      OFF`, empty registry) immediately after `build_app()`, so "off
      equals the capability does not exist" is enforced at build time,
      not just at call time.
- [x] Every dispatch path goes through the single interception function;
      no second execution path exists.
- [x] Call and outcome system events carry tool name, provider, duration,
      and a user-readable summary of the outbound data (what is being sent
      and to which provider) - enough for the events panel, the "where does
      my data go" answer, and later watchdog rules. Rejected/cancelled
      dispatches also publish a correlated outcome, not just successful
      ones.
- [x] `McpModuleStatusChanged` is published on every status transition,
      ordered consistently with the admission gate (see Architecture
      decision above).
- [x] Registry survives server connect/disconnect with correct contents.
- [x] `python -m pytest` passes without any real MCP server or network.

## Stop Conditions

- Stop if the MCP SDK forces a lifecycle that cannot live inside the
  engine's asyncio loop.
- Stop if clean disable proves impossible without leaking processes or
  connections.
