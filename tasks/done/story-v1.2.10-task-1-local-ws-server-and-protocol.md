# Task: Local HTTP+WS server and protocol v1

**Story:** `tasks/story-v1.2.10-ui-transport.md`
**Status:** Completed.
**Release:** v1.2.10

## Summary

Add a local HTTP+WebSocket server running in the engine's asyncio loop and
define protocol v1: message envelope with channel multiplexing, hello
handshake, `state` channel (snapshot plus deltas), `control` channel
(commands). No UI surface migrates in this task.

## Current Boundary

- Server binds `127.0.0.1` only, ephemeral port, one-time token issued at
  startup (token in initial URL, then carried on the WS connection).
- Channels implemented: `state`, `control`. The envelope has an explicit
  channel field so later channels (audio) need no format change.
- Handshake: the first client message declares client identity and
  capabilities; the server replies with protocol version and a full state
  snapshot.
- `state` payloads are JSON projections of `ui_contract.py` values (runtime
  state, module health, data locality, model label, system events).
- `control` commands map onto the operations `StatusConsoleApi` exposes
  today (think toggle, reset, shutdown, visibility mode). Command handling
  reuses the existing engine paths; no new engine behavior.
- The server subscribes to the bus like any other component; `bus.py` is
  not modified.
- Dependency: one library (`aiohttp` preferred: HTTP and WS in one package,
  native asyncio). Update `requirements.txt` in the same commit.
- No UI migration, no static-file rewiring of existing surfaces yet.

## Acceptance Criteria

- [ ] Server starts and stops cleanly inside the engine asyncio loop.
- [ ] Connection without a valid token is rejected.
- [ ] Handshake precedes any state or control traffic; a client that skips
      it is disconnected with a clear error.
- [ ] New client receives a full snapshot, then deltas as bus events arrive.
- [ ] Control commands reach the same engine paths as the current `js_api`
      methods and publish the same system events.
- [ ] Protocol serialization, snapshot/delta logic, token check, and
      handshake ordering are covered by pure tests (no real window, no
      hardware).
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- A throwaway WS client in tests (aiohttp test utilities) exercises the
  full connect-handshake-snapshot-delta-command cycle.

## Stop Conditions

- Stop if command handling cannot reuse the existing `StatusConsoleApi`
  paths without duplicating engine logic.
- Stop if server lifecycle conflicts with `webview.start()` ordering in a
  way that requires changing engine startup architecture.
