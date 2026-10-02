# Plan: task v2.0-5 executed by subagents

**Status:** Completed. (2026-10-03)
**Card:** `tasks/done/task-v2.0-5-mcp-server-speak-tool.md`.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Branch:** `feat/v2.0-5-mcp-server-speak-tool` from `main` (`c935506`).

## Roles

- **Orchestrator (main session).** Owns the card boundary, the open
  decisions, the stop conditions, and the acceptance checklist. Reads gate
  reports, diffs, and verdicts, never SDK or uvicorn internals. Every
  subagent prompt is self-contained: card path, this plan's relevant phase,
  the file allowlist, and the escalation triggers.
- **Spike agent** (phase 0): read-only on the repo, scratch scripts only in
  the session scratchpad. Answers yes/no questions with `file:line` evidence
  and a minimal repro.
- **Implementer** (phase 2): one agent, sequential slices, TDD. Does not
  commit.
- **Verifier** (phase 3): a fresh agent that never saw the implementer's
  reasoning. Gets the card, this plan, the gate report, and the diff.

## What the orchestrator keeps in focus

Primary (decides go / stop / correct):
1. The boundary: one endpoint, one token, one tool; the tool only validates
   and enqueues. No speech, no journal writes, no second tool.
2. The seam with task 4: `McpServerRunner` / `serve_no_mcp_server` /
   `_start_mcp_mode` / `_stop_mcp_mode` in `src/jarvis/app.py`. Task 4 stops
   the server by `task.cancel()`; the card says stop uvicorn via
   `should_exit`. The runner must turn cancellation into a graceful
   `should_exit` and finish before `voice_guide.close()` runs.
3. The open questions below and the gate results.
4. The acceptance criteria, item by item.

Secondary (delegated; reaches the orchestrator only as a verdict):
fixture mechanics, SDK client usage in tests, ruff noise, exact wording of
the tool description (checked against the card's content list, not
polished by the orchestrator).

## Escalation triggers for every subagent

Stop and report instead of working around it when:
- any card stop condition fires;
- a change is needed outside the file allowlist, in particular
  `src/jarvis/dialog/voice_guide.py`, `src/jarvis/journal/*`, or
  `src/jarvis/ui/*` (task 6);
- the `VoiceGuideService` API (`enqueue`, `VoiceGuideRequest`,
  `EnqueueResult`) does not fit as is;
- the same fix is attempted a second time (CLAUDE.md 0.7);
- tooling or environment errors (CLAUDE.md 0.9).

## File allowlist

New: `src/jarvis/mcp_mode/__init__.py`, `token.py`, `speak.py` (argument
validation and result mapping, transport-free), `server.py` (FastMCP app,
bearer middleware, socket, uvicorn lifecycle, status event);
`tests/test_mcp_mode_server.py`, `tests/test_mcp_mode_token.py`,
`tests/test_mcp_mode_speak.py` (split accepted at S1-S2 review).
Edit: `src/jarvis/app.py` (the server-runner slot and the startup-failure
path only), `requirements.txt` (`uvicorn>=0.37`, `starlette>=0.52`, the
installed versions), `PROJECT.md` (server facts in "Architecture v2.0",
same commit, as tasks 2-4 did).

## Phase 0: gate checks (spike, before any code)

Each item is a card stop condition or a verified trap. Output: one short
report, `yes / no / mitigation` per item with evidence.

- G1. Claude Code sends a static `Authorization` header to an HTTP MCP
  server (`claude mcp add --transport http ... --header`). The `claude` CLI
  is not on PATH in this shell; ask a `claude-code-guide` agent for the
  documented flag, and the owner confirms with `claude mcp add --help`.
- G2. `clientInfo` is reachable from a tool handler through public API
  (`Context.session.client_params.clientInfo`; `client_params` exists in
  `mcp/server/session.py`), and the `mcp-session-id` header through
  `Context.request_context.request`.
- G3. `streamable_http_app()` serves inside an already running loop through
  `uvicorn.Server(config).serve(sockets=[...])`, both on the main thread and
  on a non-main thread (the `--status-console` engine thread), and the
  session manager lifespan starts and stops cleanly.
- G4. Signals. Verified: `uvicorn.Server.capture_signals()` replaces the
  SIGINT/SIGTERM handlers when it runs on the main thread (plain
  `--mcp-mode`, no Status Console) and re-raises captured signals on exit.
  That would take Ctrl+C away from Jarvis. Expected mitigation: a subclass
  that overrides `capture_signals` as a no-op. See question Q3.
- G5. Port in use. Verified: on bind failure uvicorn logs and calls
  `sys.exit(1)`, i.e. `SystemExit` inside our task. Expected mitigation: bind
  the socket ourselves (`127.0.0.1`, configured port, port 0 for tests),
  raise a typed error naming the port and `[mcp_mode].port`, pass
  `sockets=[sock]` to `serve()`. Also check Windows semantics: a second bind
  to a held port must fail (no `SO_REUSEADDR` port sharing).
- G6. Cancellation: what `task.cancel()` does to `serve()`, and the shape
  that converts it to `should_exit` and waits for a clean exit, with an open
  client session (the SDK's Python client opens the standalone GET SSE stream
  after initialize, so the test client exercises it).
  Verified by reading (2026-10-02): the standalone GET stream lives as long as
  the client session. sse-starlette 3.4.5 closes it on shutdown only through
  uvicorn's `handle_exit` or by finding the uvicorn server in the SIGTERM
  handler, i.e. only when uvicorn owns the signals on the main thread. Our
  `should_exit` path (and the Status Console engine thread) is invisible to
  it, and uvicorn's graceful shutdown waits for that connection with no
  default timeout: a deterministic hang. Proposed fix (Q4): no long-lived
  streams at all, plus a bounded `timeout_graceful_shutdown` as a safety net.
- G7. Host validation: `FastMCP(host="127.0.0.1")` enables
  `TransportSecuritySettings` by default; a request with a valid token and a
  foreign `Host` is rejected (status code recorded for the test).
- G8. Logging: what the SDK and uvicorn log at DEBUG for one `speak` call
  (`log_config=None`, `access_log=False`); whether any record contains the
  token or the canvas.

Orchestrator decision after phase 0: go, go with listed mitigations, or stop
and report to the owner.

### Phase 0 results (2026-10-02)

Prototype: session scratchpad, `spike-v2.0-5/proto.py` (not in the repo).

- G1 open. Syntax exists (`--header`, `.mcp.json` `headers`).
  anthropics/claude-code#48514 (closed, resolution unknown) reported headers
  not sent on POST; anthropics/claude-code#78193 (closed as not planned,
  2.1.209): a 405 on the standalone GET makes Claude Code show a recurring
  "Client server capabilities not available" toast, tools still work.
  Checked by the orchestrator with the owner's permission, Claude Code
  2.1.247, prototype `serve --get serve`: `claude mcp list` -> Connected;
  every POST and the standalone GET carried the header and it matched
  (12 requests). G1 pass for the header. After the owner re-logged in, a
  real `claude -p` run called `speak` and got `{"status": "queued",
  "position": 1}`; the server saw `clientInfo=claude-code/2.1.247` with the
  header matched. Not observed: a DELETE. Each connection's first POST got 400 from
  the SDK and the retry succeeded; harmless here, cause not investigated.
- G2 pass: `ctx.session.client_params.clientInfo`;
  `ctx.request_context.request.headers.get("mcp-session-id")`. Both None
  under `stateless_http=True`, so stateful mode (the default) is required.
- G3 pass: main thread and engine thread, stop in ~0.2 s.
- G4 pass: the override keeps SIGINT/SIGTERM/SIGBREAK handlers unchanged.
- G5 pass: a held 127.0.0.1 port gives `OSError` errno 10048, with or
  without the holder's `SO_REUSEADDR`. A `0.0.0.0` holder does not block our
  127.0.0.1 bind; loopback traffic then reaches us, which is correct.
- G6 pass with mitigation: a bare `task.cancel()` skips uvicorn `shutdown()`
  (port keeps accepting, lifespan never stops). Runner shape: shield the
  serve future, on `CancelledError` set `should_exit`, await serve,
  re-raise.
- G6b (GET stream served, client connected): no timeout = hang (confirmed);
  `timeout_graceful_shutdown` 1 s / 2 s = 1.2 s / 2.3 s plus two ERROR
  records per shutdown; sse-starlette `AppStatus.should_exit` = 0.6 s but
  an ERROR record and sticky process-wide (contaminates later servers,
  rejected); `StreamableHTTPServerTransport.terminate()` (public) on each
  session reached through the private `session_manager._server_instances`
  = 0.21 s, clean logs.
- G7 pass: foreign Host with a valid token -> 421; foreign Origin -> 403;
  no/wrong token -> 401.
- G8 pass: no token in any record; the canvas appears only in the client
  side `mcp.client.streamable_http` DEBUG record, never on the server.
- Implementation constraints found: `FastMCP.__init__` calls
  `logging.basicConfig(level=INFO)` with a RichHandler, a no-op only if root
  already has handlers, so logging must be configured before FastMCP is
  built; `session_manager.run()` runs once per instance, so every server
  start builds a fresh FastMCP.

## Decisions

Owner decisions, 2026-10-02 (the proposals they answered are not kept here):
- Q1: token read and socket bind happen synchronously before
  `voice_guide.start()`. On failure: plain mode exits non-zero with the
  message; with `--status-console` Jarvis keeps running, the guide is not
  started, `FAILED` with the reason is published, and the reason is shown
  through the existing `publish_system_event` path (the dedicated server
  state widget is task 6). Allowlist: `src/jarvis/ui/text.py` for the
  failure message keys only.
- Q2: error code `closed`.
- Q3: option A, the `capture_signals` override.
- Q4 (revised after G1/G6b; answering GET with 405 was rejected because
  Claude Code then shows a recurring error toast): serve the GET
  stream; on stop, call the public `StreamableHTTPServerTransport.terminate()`
  on each session found through the private
  `session_manager._server_instances` before `should_exit`; keep
  `timeout_graceful_shutdown = 2` as a safety net. A test stops the server
  with an open GET stream and asserts it takes under 1 s with no ERROR
  record, so an SDK rename fails CI loudly. `json_response=True` stays.

Orchestrator decisions at phase 2 start (small, reversible; reported to the
owner):
- `VoiceGuideAccepted` gains `speech_origin`, filled by `enqueue()` from the
  existing `_origin_of()`, so the tool result never re-derives the rule.
  Allowlist: that field in `src/jarvis/dialog/voice_guide.py` and the
  equality assertions it touches in `tests/test_voice_guide.py` and
  `tests/main_split/test_main_mcp_mode.py`.
- A whitespace-only `canvas` is `empty_canvas`; a provided but
  whitespace-only `spoken_text` is a new code `empty_spoken_text` (it would
  otherwise select the `caller` origin with nothing to speak); a
  whitespace-only `guidance` is treated as absent. Lengths are `len()` in
  characters, as `config.example.toml` documents.
- The task 4 seam changed shape for Q1's synchronous prepare step and for
  listener ownership: `run(prepare_mcp_server: McpServerPreparer)`, where the
  preparer `(McpModeSettings, VoiceGuideService, EventBus) -> McpServer`
  reads the token and binds the port, and `McpServer.start()` returns the
  `mcp-server` task. Task 4's tests inject a stub preparer.

Owner decision after verification, 2026-10-02: SDK floor `mcp>=1.30,<2`
(1.30's idle timeout and session cap bound session growth; 2.x removes
`mcp.server.fastmcp`). The 2.x migration is
`tasks/backlog/mcp-sdk-2x-migration.md`.

## Phase 1: branch

`git switch -c feat/v2.0-5-mcp-server-speak-tool`.

## Phase 2: implementation (one implementer, TDD, slices in order)

Each slice ends green on `python -m pytest <its tests>`, and the implementer
returns a five-line summary: files touched, tests added, deviations,
escalations. The orchestrator reviews the summary and, at S3 and S4, the
diff, before the next slice.

- S1. Token file: read existing; create with `secrets.token_urlsafe(32)` if
  missing; empty or unreadable is an error whose message names the path,
  never the token. Relative path = working directory (config.example.toml).
- S2. `speak` logic without transport: argument checks in card order
  (`empty_canvas`, `canvas_too_long`, `spoken_text_too_long`,
  `guidance_too_long`), `VoiceGuideRequest` construction with the caller,
  `EnqueueResult` -> result (`queued`, `position`, `speech_origin`,
  `guidance_ignored`) or typed error (`queue_full`, Q2's code). The
  speech origin must come from the same rule the service uses; if the
  service does not expose it, escalate (do not duplicate the rule).
- S3. Server: FastMCP with the one tool and the card's description, bearer
  middleware (`hmac.compare_digest`, plain 401, mirrors `token_matches()` in
  `src/jarvis/ui/transport.py`), host validation on, socket bind, uvicorn
  lifecycle per G3-G6, status events `LISTENING(port)` / `STOPPED` /
  `FAILED(reason)`.
- S4. Wiring in `app.py` per Q1 and the runner factory; replaces
  `serve_no_mcp_server` as the production default (the stub may stay for
  tests if task 4's tests use it). `requirements.txt`. `PROJECT.md` server
  facts.

## Phase 3: verification (fresh verifier)

- Gates: `python -m pytest`, `ruff check`, `ruff format --check` (all three;
  CI runs format separately).
- Acceptance criteria one by one, each with the test name or command that
  proves it.
- Adversarial checks: token string absent from every log record at DEBUG,
  in exception text, and in UI payloads; foreign `Host` tested with a valid
  token (otherwise the 401 masks the host check); the tool result arrives
  before any speech call; cancellation leaves no running task and frees the
  port (a second start on the same port succeeds); diff stays inside the
  allowlist.
- Output: pass/fail per item, with findings ranked by severity. The
  orchestrator decides fix-or-defer; confirmed races are fixed in this task,
  not deferred.
- Optional second opinion: `/code-review high` on the branch diff.

## Phase 4: handoff to the owner

The card has no hardware-dependent tests (loopback only, CI-safe), so there
is no human-run handoff here; the real Claude Code call is task 8's. The
owner gets: the summary, the gate report, decisions taken, the diff, and
the G1 confirmation command. No commit, card closing, or merge before the
owner's review.
