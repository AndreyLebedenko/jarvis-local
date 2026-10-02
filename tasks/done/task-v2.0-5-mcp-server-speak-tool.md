# Task v2.0-5: MCP server and the `speak` tool

**Status:** Completed. (2026-10-03; see completion notes below.)
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Depends on:** task-v2.0-3 (`VoiceGuideService.enqueue()`) and
task-v2.0-4 (`[mcp_mode]` config, the server-runner slot in `run()`).
**Executor:** the story's executor profile. This card is the network-facing
boundary: one localhost HTTP endpoint, one token, one tool. The tool only
validates and enqueues. If you find yourself generating speech, touching the
journal, or adding a second tool, you have left this card - stop.

## Summary

Serve a streamable-HTTP MCP server with the `mcp` SDK (already in
`requirements.txt`, installed 1.28.1). It is bound to `127.0.0.1` on the
configured port and protected by a static bearer token and the SDK's
host/origin validation. It exposes one tool,
`speak(canvas, spoken_text?, guidance?)`, which validates its arguments,
enqueues a `VoiceGuideRequest`, and returns "accepted, queued" at once.

## Why this exists

Settled constraints 4-7 (owner): a long-lived localhost streamable-HTTP
server, not stdio; token-authenticated; one non-blocking queued tool; Jarvis
sends nothing outward.

## Design notes for the executor (verified against the installed SDK)

- **Bearer token: our own ASGI middleware, not the SDK's OAuth path.**
  `FastMCP` accepts a `token_verifier`, but only together with `auth`
  settings (`AuthSettings` with issuer and resource-server URLs). That
  switches the server into OAuth resource-server behavior: protected-resource
  metadata and `WWW-Authenticate` challenges that invite a client to start an
  OAuth flow. A static local token needs none of that. Wrap
  `FastMCP.streamable_http_app()` in a small ASGI middleware that rejects any
  request without `Authorization: Bearer <token>` with a plain 401. Compare in
  constant time, mirroring `token_matches()` in `src/jarvis/ui/transport.py`
  (`hmac.compare_digest`).
- **Host/origin validation stays on.** `FastMCP` enables
  `TransportSecuritySettings` DNS-rebinding protection automatically when
  `host` is `127.0.0.1`. Keep it, and assert it in a test, because it is the
  second boundary after the token.
- **Same event loop.** Run the Starlette app with `uvicorn.Server(...)
  .serve()` as a task in Jarvis's own asyncio loop. With `--status-console`
  that loop runs in the engine thread, not the main thread. Stop via
  `should_exit`. Configure uvicorn's logging to go through Jarvis's logging
  and never log request bodies. The server package imports `uvicorn` and
  `starlette` directly, so add both to `requirements.txt` with lower bounds
  matching the installed versions (tooling note 3), instead of relying on the
  `mcp` dependency tree.
- **Caller identity.** In the tool handler, take `clientInfo` (name,
  version) from the session's initialize parameters and the transport session
  id from the `mcp-session-id` request header. Both are nullable. They go into
  `VoiceGuideRequest` for task 2's metadata.

## Required reading before implementing

- The installed SDK: `mcp/server/fastmcp/server.py` (`FastMCP.__init__`
  `transport_security` defaulting, `streamable_http_app()`,
  `run_streamable_http_async()` as a reference for the uvicorn setup) and
  `mcp/server/transport_security.py`.
- `src/jarvis/ui/transport.py`: `token_matches()` and how the UI transport
  keeps its token out of logs.
- `src/jarvis/dialog/voice_guide.py` (task 3) and the `[mcp_mode]` settings
  (task 4).
- `examples/mcp/ddgs_get_mcp.py`, the repo's existing MCP server example, for
  local conventions.

## What to build

1. **Token file lifecycle** (`src/jarvis/mcp_mode/token.py` or similar):
   - on start, read the token from `[mcp_mode].token_file`. If the file is
     missing, generate `secrets.token_urlsafe(32)` and write it;
   - an unreadable or empty file is a startup error with a clear message,
     never silent regeneration (that would break the user's client config
     without telling them);
   - the token is never logged, never put in a UI payload, and never in an
     exception message.
2. **Server module** (`src/jarvis/mcp_mode/server.py` or similar):
   - builds the `FastMCP` app with the one tool, wraps it in the token
     middleware, and serves it on `127.0.0.1:<port>`;
   - the port is injectable for tests (port 0 = ephemeral);
   - a port already in use fails startup with a message naming the port and
     the config key `[mcp_mode].port`, never a silent fallback to another
     port (the client's stored URL would then point at nothing);
   - publishes a server status event (`LISTENING` with port, `STOPPED`,
     `FAILED` with reason) for task 6;
   - replaces task 4's server stub in `run()`.
3. **The `speak` tool:**
   - input schema: `canvas` (string, required), `spoken_text` (string,
     optional), `guidance` (string, optional);
   - validation, each failure a tool error result (`isError: true`) with a
     stable machine-readable code in its text: `empty_canvas`,
     `canvas_too_long`, `spoken_text_too_long`, `guidance_too_long`,
     `queue_full` (from `enqueue()`). Limits come from `[mcp_mode]`. A
     rejected call is not journaled;
   - `guidance` together with `spoken_text` is accepted. The guidance is
     journaled but unused, and the result says `guidance_ignored: true`, so
     the caller learns without losing the call;
   - success result, returned immediately without waiting for speech:
     `{"status": "queued", "position": <1-based>, "speech_origin":
     "derivative" | "verbatim" | "caller"}`;
   - tool description (model-facing, English): what Jarvis does with the
     call (speaks a short guide aloud on the user's machine and stores the
     answer in the user's local journal); that it returns before speaking;
     that the canvas should be the full answer as shown to the user, keeping
     headings and `file:line` references, because the guide names them as
     landmarks (resolved question 3); when to use `spoken_text` and
     `guidance`; and the length limits.

## Explicitly out of scope

- A second tool, resources, prompts, or sampling.
- A Claude Code `Stop` hook or any CLI client (resolved question 4).
- OAuth, multiple tokens, token rotation UI (deleting the file rotates it).
- Binding to anything but `127.0.0.1`.

## Tests

`tests/test_mcp_mode_server.py` (new). Run the real server on
`127.0.0.1:0`, connect with the SDK's streamable-HTTP client
(`mcp.client.streamable_http`), and use a fake `VoiceGuideService`.
Loopback only and no external network, so this is CI-safe under the runtime
locality contract.

- Without a token, and with a wrong token: 401, the tool is never reached.
- With the right token: `tools/list` shows exactly `speak` with the schema
  above.
- `speak` with a canvas enqueues one request with the caller's `clientInfo`
  and session id, and returns `queued` with its position without awaiting any
  speech (the fake service's enqueue returns immediately, and the test
  asserts no speech call happened before the result).
- Each validation code, including `queue_full` from the fake.
- `guidance` + `spoken_text` -> accepted, `guidance_ignored: true`.
- A request with a foreign `Host` header is rejected by transport security.
- Token file: created on first start, reused on the second, an empty file is
  a startup error; the token string appears in no captured log record.
- Port in use: startup fails with the port and config key in the message.

## Acceptance criteria

- [x] The server listens only on `127.0.0.1:<[mcp_mode].port>`, rejects
      requests without the bearer token and requests with a foreign `Host`.
- [x] `speak` validates, enqueues, and returns `queued` with its position
      immediately; invalid calls get typed error codes and are not journaled.
- [x] The token persists across runs in `[mcp_mode].token_file`, is never
      logged or shown, and a broken token file fails loudly.
- [x] `uvicorn` and `starlette` have lower bounds in `requirements.txt`.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` green.

## Stop conditions

- Stop if the SDK's streamable-HTTP app cannot run inside Jarvis's existing
  event loop (for example it requires its own thread, process, or the main
  thread for signal handling). The threading model is an architectural choice
  to raise.
- Stop if the token cannot be checked in front of the SDK app without forking
  or patching the SDK.
- Stop if Claude Code turns out not to send a static `Authorization` header
  to a streamable-HTTP server (check `claude mcp add --help` for `--header`
  before building). The auth design would then have no client.
- Stop if session initialize parameters (`clientInfo`) are not reachable from
  a tool handler through the SDK's public API. Record the caller as unknown
  only with the owner's agreement.

## Completion notes (2026-10-03)

Executed by subagents under `tasks/done/plan-v2.0-5-subagent-execution.md`,
which records the phase-0 gate results and every owner decision. Deviations
from this card, all owner-approved:

- The standalone GET stream is served (a 405 makes Claude Code show a
  recurring error toast, anthropics/claude-code#78193). On stop, sessions are
  terminated through the SDK's private `session_manager._server_instances`
  before uvicorn's `should_exit`; a test guards it.
- uvicorn is subclassed: `capture_signals` is a no-op (signals stay with
  Jarvis) and `startup` is overridden to close two startup races.
- A startup failure (token file, busy port) exits headless runs with code 4;
  with `--status-console` Jarvis keeps running and reports `FAILED`.
- Extra error codes: `empty_spoken_text`, `closed`. `VoiceGuideAccepted`
  carries `speech_origin` so the tool never re-derives it.
- SDK floor `mcp>=1.30,<2`: 1.30's idle timeout and session cap bound
  session growth. The 2.x migration is
  `tasks/backlog/mcp-sdk-2x-migration.md`.
- Verified against Claude Code 2.1.247: the bearer header arrives on every
  request and a real `speak` call returns `queued`.

Server facts are recorded in `PROJECT.md`, "Architecture v2.0".
