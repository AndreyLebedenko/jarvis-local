# Story: Kling video MCP - PoC

**Status:** Design fixed, blocked. Umbrella feature.
**Depends on:**
- `story-v1.8.1-session-file-operations.md` - the full session file capability
  including its persistent UI upload slice. Kling needs the user-marked frame
  to exist as a session file, not only the pure repository.
- `spike-kling-integration.md` - must complete first; it closes the three
  live unknowns (transport, `file_upload` input form, `who_am_i` schema)
  this story's Kling leg is designed against.

## User-facing goal

The user attaches an image frame in the chat and asks Jarvis to render an
animation from it via Kling. Jarvis composes the animation prompt, submits
the render to Kling, and on a later "is it ready?" turn either reports "not
yet" or downloads the finished video into the session, verifies it locally
with ffprobe, and reports the real result.

Target render for the PoC: single start frame, 9:16, 720p, 5 s, no audio.

## Settled architecture

### Attachment I/O

Provided by `story-v1.8.1-session-file-operations.md` - not restated here. The
frame is a session file the user marks and the model reads/views by
`storage_name`; `kling_submit` resolves that storage name to bytes off the
token stream through the same session-file repository. PoC default: the
marked input frame is auto-inlined to vision AND its `storage_name` is
surfaced, so the model both sees it and holds a handle.

### Kling submit/check (all Kling-specific knowledge concentrated here)

- `kling_submit(storage_name, prompt, duration, aspect_ratio, resolution,
  enable_audio) -> render_ref`. Internally, off the model's token
  stream:
  1. resolve the storage name to bytes via the session-file repository;
  2. mint one `taskTraceId` (UUID v7) for the whole chain;
  3. `who_am_i` -> live model schema; pick the single-frame model
     (`kling-video-v3_0_turbo`, no tail); validate every argument is
     declared by that model in the current schema, else return an explicit
     error (do not send);
  4. `file_upload(frame bytes)` -> mandatory Kling URL (a local path or
     external link does not substitute it - per the MCP spec);
  5. `image_to_video` with the uniform envelope
     `{model, arguments:[{name,value}...], inputs:[{name,inputType:"URL",
     url}], rationale, taskTraceId}` - all values as strings.
  Returns only an opaque `render_ref` to the model. The ref is a compact
  self-contained token carrying the minimum follow-up state Jarvis needs
  (`generation_id`, `taskTraceId`, provider id, and originating
  `session_id`) plus an HMAC/signature so edited or fabricated refs are
  rejected before any provider call. The Kling URL and raw envelope never
  surface.
- `kling_check(render_ref) -> status | result_url`, wrapping `query_tasks`
  with the `generation_id` and `taskTraceId` decoded from the opaque ref.
- No auto-retry on failure/timeout/unexpected result: report and wait for
  the user (per the MCP spec).

### Result write-back and verification (local, provider-agnostic)

- `media_fetch(result_url) -> {storage_name, bytes} | is_error`. One
  responsibility: download from a **Kling CDN host allowlist** (the URL is
  observed content) + hand the media data to the session-file repository's
  internal `write_bytes` + return the `storage_name`/`bytes`.
  - Extension is derived from the response `Content-Type` validated against
    an expected-type allowlist, never from the URL tail. **PoC: hardcode
    `.mp4`.**
  - Stream to a temp file, then atomic rename; a partial download must never
    be visible as a valid attachment. Storage-name generation belongs to the
    repository, not to `media_fetch` - it only supplies the requested output
    name and the finished media data.
  - Signal to the model is `storage_name` (same form as the read side) +
    size in bytes - not an absolute path, not the bytes.
  - Safety size cap; unexpected Content-Type / non-terminal status / abort /
    over-cap -> `is_error`, no file written.
- `media_probe(storage_name) -> facts` (separate tool, SRP): ffprobe reports actual
  width/height, aspect ratio, fps, duration, and audio-stream presence - by
  fact, not by claim. Divergence from the request is reported honestly, not
  passed off as success. The ffprobe subprocess is behind an injected runner:
  pure tests cover command-result parsing from captured output, while the real
  binary path and Windows availability are verified only in the manual
  handoff.

## Boundaries / non-goals (PoC)

- No render-job ledger. The last opaque `render_ref` lives in the model's
  context (accepted trade-off); it is self-contained enough for
  `kling_check` to recover the provider id, originating session id,
  `generation_id`, and `taskTraceId`, and integrity-protected enough to reject
  model/user edits. It is not a durable job store and does not promise
  recovery after restart.
- No proactive "your video is ready" notification. The flow is turn-based
  ("check if it is ready"); proactive delivery is the deferred dual-context
  blocker and is out of scope.
- Do not import the Dream Me In production workflow (approval gates,
  archiving, folder layout). Only its tool names, envelope, and mandatory
  sequence are authoritative here.
- Locality: Kling is an explicit per-component capability, off by default,
  honest on the data-source axis - per PROJECT.md's runtime locality
  contract. Node (`mcp-remote`) is acceptable for the PoC.

## Open decisions before implementation

1. **builtin -> MCP host coupling.** `kling_submit`/`kling_check` must call
   Kling MCP tools, so they need a reference into the MCP host/dispatcher,
   which builtins in `src/jarvis/tools/host.py` do not have today. This new
   seam is a prerequisite. The call path should go through
   `McpHost.dispatcher.dispatch()` rather than directly to `McpClient`, so it
   preserves tool enablement, provider admission, transport-error handling,
   and audit events. The seam problem is construction order only: `McpHost`
   receives builtin clients today, so this needs a late-bound dispatcher
   reference or equivalent small indirection. The rejected alternative (model
   drives the raw MCP envelope + UUID v7 itself) is too fragile on a small
   local model.

2. **Live Kling unknowns** - extracted to `spike-kling-integration.md`
   (transport, `file_upload` input form, live `who_am_i` schema). That spike
   must complete before this story's Kling leg is implemented.

## Proposed ordered task sequence

Prerequisites (separate work, not tasks of this story):
- `story-v1.8.1-session-file-operations.md` delivers the complete session file
  capability, including persistent UI upload.
- `spike-kling-integration.md` closes the live Kling unknowns.

This story's own tasks:
1. `media_fetch` (Kling CDN allowlist, atomic write into the session via the
   session-file repository, `.mp4` hardcoded) + `media_probe` parser and
   injected ffprobe runner seam (pure tests use captured ffprobe output, no
   Kling or real ffprobe).
2. builtin -> MCP host seam (open decision 1).
3. `kling_submit` / `kling_check` on top of the spike findings and the seam,
   including opaque `render_ref` encode/decode.
4. End-to-end PoC wiring + system-prompt orchestration; manual hardware/live
   handoff (Ollama, live Kling, ffprobe) per the testing protocol.
5. Documentation/release note - update `PROJECT.md` with the final Kling PoC
   architecture and data-source/locality statement in the same commit as the
   implementation.

## Acceptance criteria

- `media_fetch` writes atomically through the repository's `write_bytes`,
  rejects a disallowed host and an unexpected Content-Type, and returns
  `{storage_name, bytes}` (pure test with a fake HTTP source).
- `media_probe` parses ffprobe output into real container facts and flags a
  mismatch (pure test with captured ffprobe output; real binary execution is
  manual).
- `kling_submit` builds the correct envelope with a single `taskTraceId`,
  resolves the frame off the token stream, validates arguments against a
  `who_am_i` schema, and returns an opaque `render_ref`; `kling_check`
  decodes that ref and uses the same `taskTraceId` when calling
  `query_tasks`; tampered refs are rejected before any provider call (pure
  test with a fake MCP client).
- Manual live handoff: real frame -> render -> "check" -> download -> ffprobe
  records actual width/height, aspect ratio, fps, duration, and audio-stream
  presence; width/height 720x1280, 9:16, 5 s, and no audio are expected for
  the PoC, while fps is reported factually unless the spike/live schema proves
  it is controllable.
