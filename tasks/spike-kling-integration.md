# Spike: Kling MCP integration check

**Status:** Not started.
**Type:** Investigation spike. No production code. Human-run (OAuth + live
Kling account). Output is a written findings note, not a merged feature.

## Question

Before committing to the Kling render PoC design, verify how the Kling MCP
actually behaves on a live connection. The design in
`story-kling-video-mcp-poc.md` has live unknowns that cannot be closed at the
desk; this spike closes them.

## What we already know (from the vendor spec, do not re-verify)

`D:\AI\Video\DreamMeIn\KLING_MCP_SPEC.md` gives the tool set (`who_am_i`,
`file_upload`, `image_to_video`, `query_tasks`, ...), the uniform call
envelope (`{model, arguments:[{name,value}], inputs:[{name,inputType:"URL",
url}], rationale, taskTraceId}`), the mandatory sequence, and that
`file_upload` returns a Kling URL that a local path/external link cannot
substitute. Treat these as given.

## Unknowns to close

1. **Transport.** Is `https://kling.ai/mcp` a remote HTTP MCP driven via a
   local `mcp-remote` stdio bridge, or does it expect a locally-run server?
   This decides whether Jarvis's stdio-only `StdioMcpClient`
   (`src/jarvis/tools/mcp_client.py`) reaches it as-is via `mcp-remote`, or
   whether a native HTTP client is needed.
2. **`file_upload` input form.** Does the tool take base64 content or a
   local path? Base64 means the upload must run in-code off the model's
   token stream; a path implies a locally-running server with filesystem
   access. Snap the `inputSchema`.
3. **Live `who_am_i` for the account.** Which models and which per-model
   arguments are actually allowed - in particular whether `720p` is a
   `resolution` value or is implied by `mode`, and whether `enable_audio`
   is honored for the single-frame model.
4. **OAuth/session persistence.** Where does `mcp-remote`/Kling store the
   OAuth token after browser login, does it survive a Jarvis restart, and what
   is the observable failure mode when it expires or is revoked?

Also record, if cheap: whether Kling exposes its own status/download tools
that would move part of the render pipeline off our side.

## Method (human handoff per the testing protocol)

1. Configure the Kling MCP server (PoC: `mcp-remote` over
   `https://kling.ai/mcp`) and complete the OAuth flow in a browser.
2. Call `who_am_i`; capture the returned model schema.
3. Snap `inputSchema` for `file_upload` and `image_to_video`.
4. Restart the bridge/Jarvis-side MCP process and call `who_am_i` again to
   record whether the OAuth session persists without another browser flow.
5. Record findings in this file (or a sibling note); do not build production
   code from them yet - that is the Kling PoC story's job.

## Done when

The unknowns above are answered with captured evidence, and
`story-kling-video-mcp-poc.md`'s "Open decisions before implementation" item
2 can be marked resolved.
