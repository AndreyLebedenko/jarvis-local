# Task: migrate to MCP Python SDK 2.x

**Status:** Backlog.
**Target:** after v2.0.
**Origin:** task v2.0-5 verification, 2026-10-02.

## Summary

Jarvis pins `mcp>=1.30,<2`. SDK 2.x (2.0.0 onward; 2.3.0 current on
2026-10-02) natively supports protocol revision 2026-07-28, including
`server/discover` and handshake-free stateless requests, but removes
`mcp.server.fastmcp` in favor of a different `MCPServer` API.

Why it matters: Claude Code 2.1.x first sends a 2026-07-28
`server/discover` POST. SDK 1.x answers it with 400 "Missing session ID" and
the client falls back to `initialize`. That works, but every connection pays
one failed round trip and leaves an orphan session until the 1.30 idle
timeout (30 minutes) reaps it.

## Current Boundary

- Both MCP sides move together: the `--mcp-mode` server
  (`src/jarvis/mcp_mode/server.py`) and the MCP client
  (`src/jarvis/tools/mcp_client.py`).
- Re-verify everything the server relies on from SDK internals or
  behavior, recorded in `PROJECT.md` "Architecture v2.0": the private
  `session_manager._server_instances` used at shutdown, `client_params`
  for caller identity, host/origin validation, `json_response`, the GET
  stream, the FastMCP `basicConfig` guard.
- Decide whether to keep stateful sessions: caller identity
  (`clientInfo`, transport session id) depends on them in 1.x.

## Acceptance Criteria

- [ ] `requirements.txt` moves to `mcp>=2.x,<3` in the same commit as the
      code change.
- [ ] A Claude Code connection no longer gets a 400 on its first request.
- [ ] Caller identity still reaches the journal metadata.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.
