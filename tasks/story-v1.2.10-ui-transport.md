# Story v1.2.10: UI Transport

**Status:** Planned.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.10
**Vision:** `VISION.md`, section "Component Model (Jarvis 2.0 direction)".

## User-facing goal

All UI surfaces (Status Console, touchstrip, future Control Center dashboard)
talk to the engine through one local HTTP+WebSocket server instead of the
pywebview `evaluate_js`/`js_api` bridge. The same UI becomes reachable from an
ordinary browser at a loopback URL, which makes visual QA and future dashboard
work cheap. pywebview remains only a window shell.

## Why now

This is the architectural prerequisite for v1.3.0 Control Center, extracted
into a v1.2.x preparation release per the roadmap rule "one major
architectural output per release". The transport is also the first concrete
step toward the component model direction in `VISION.md`: the protocol is
designed so that a later remote surface or component node does not require a
protocol rewrite.

## Boundaries

- Loopback only: the server binds `127.0.0.1` with an ephemeral port and a
  one-time token. LAN binding, pairing, and node authentication (mTLS) are
  out of scope.
- Channels implemented: `state` and `control` only. The message envelope
  reserves channel multiplexing so audio channels can be added later without
  a format change, but no audio work happens here.
- No same-process or same-machine assumptions in the protocol design, while
  shipping loopback-only.
- No visual changes to existing surfaces: the Status Console and touchstrip
  must look and behave exactly as before the migration.
- The in-process event bus (`bus.py`) is unaffected. The server is a bus
  client that projects bus traffic to WS clients; Jarvis does not implement
  a distributed bus.
- Runtime locality guarantee is preserved: listening on loopback is not
  outbound network access. This must be recorded in `PROJECT.md`.

## Acceptance Criteria

- [ ] One local server serves UI static files and holds WS connections for
      all UI surfaces.
- [ ] Protocol v1 starts with a hello/handshake message in which the client
      declares its identity and capabilities.
- [ ] The `state` channel delivers a full snapshot on connect and deltas
      afterwards, carrying the existing `ui_contract.py` values.
- [ ] The `control` channel carries the commands currently exposed through
      `js_api` (think toggle, reset, shutdown, visibility mode).
- [ ] Status Console and touchstrip run through the server with pixel-level
      visual parity; the `evaluate_js`/`js_api` bridge is removed.
- [ ] The same URL opened in Chrome shows a working, controllable console.
- [ ] `python -m pytest` passes; protocol logic is covered by pure tests.
- [ ] `PROJECT.md` records the loopback guarantee and the transport decision.

## Task Card Sequence

1. `story-v1.2.10-task-1-local-ws-server-and-protocol.md`
   Local HTTP+WS server, protocol v1 (hello, state, control), token auth.
2. `story-v1.2.10-task-2-status-console-migration.md`
   Status Console becomes a WS client; pywebview reduced to a window shell.
3. `story-v1.2.10-task-3-touchstrip-migration-and-bridge-removal.md`
   Touchstrip migrates; `evaluate_js`/`js_api` bridge code is deleted.
4. `story-v1.2.10-task-4-manual-handoff-and-docs.md`
   Manual verification (real windows plus Chrome) and documentation updates.

## Stop Conditions

- Stop if the server cannot start inside the engine's asyncio loop before
  the pywebview windows without a lifecycle conflict.
- Stop if visual parity cannot be reached without changing surface markup
  beyond swapping the transport layer.
- Stop if any command path would require keeping `js_api` alive alongside
  the WS control channel.
