# Story v2.0: MCP voice guide (`--mcp-mode`)

**Status:** Approved (owner, 2026-09-30); task cards written, none started.
**Created:** 2026-09-30
**Updated:** 2026-09-30
**Roadmap:** `tasks/roadmap-v1.9-v2.0.md` (section "v2.0 - MCP voice guide
(`--mcp-mode`)").
**Predecessors:** `story-v1.9.0-response-modes.md` (done) shipped the mode-3
two-pass contract this story reuses with an external canvas producer;
`story-v1.9.1-provenance-aware-indexing.md` (done) shipped the typed
provenance descriptor the external canvas must map onto.
**Executor profile:** same as story-v1.9.1. Task cards name files, precedents,
and boundaries literally, prefer "mirror this existing pattern" over
open-ended design, and state up front what they must NOT touch.

## Origin

Owner planning dialog, 2026-09-30. A strong external model (for example
Claude in Claude Code) produces long, dense answers that are hard to follow as
text. Jarvis becomes the local voice guide over them: it speaks the gist and
points to where the details are. The external answer never leaves the machine
through Jarvis.

Architecturally this is v1.9.0 mode 3 with the first pass replaced by an
external producer: the external answer is the authoritative canvas, and
Jarvis's spoken layer is a derivative of it (roadmap cross-cutting rule 1).

Rejected in the same dialog, not to be reopened by this story: Jarvis calling
an external LLM itself (roadmap, "Rejected for v2.0").

## User-facing goal

- The user starts Jarvis with `--mcp-mode`. Jarvis listens to no one - no
  microphone, no typed chat - and serves one local MCP tool.
- Claude Code (or any MCP client the user configures) calls
  `speak(canvas, spoken_text?, guidance?)` with its long answer. The call
  returns at once; Jarvis speaks a short guide over that answer, naming the
  sections, files, and lines the user should look at.
- Every call lands in the same Journal as normal Jarvis turns. The user can
  find it later in Journal search, annotate it, and replay what was spoken.

## Settled constraints (owner, 2026-09-30 - do not re-litigate)

1. **Single instance, now and in the future.** Normal mode and `--mcp-mode`
   never run concurrently. A second start is refused, not merely
   discouraged. Separate workspaces are not a workaround for this.
2. **No user input into the model in `--mcp-mode`.** No microphone, no typed
   chat request, no clipboard or screenshot submit.
3. **Journal search, memory, and annotations are preserved:** same journal,
   same indexes, same Status Console surfaces.
4. **Runtime locality is unchanged.** The server listens on localhost only;
   Jarvis sends nothing outward.
5. **Transport:** a long-lived streamable-HTTP MCP server, localhost-bound,
   token-authenticated. Not stdio (a stdio server lives and dies with the
   client session and would reload TTS on every start).
6. **One tool, `speak(canvas, spoken_text?, guidance?)`:**
   - `canvas` only: Jarvis produces a spoken derivative over the canvas, or
     speaks the canvas directly - chosen by a setting;
   - `spoken_text`: goes straight to TTS; `canvas` is still journaled;
   - `guidance`: added to the derivative prompt to steer it.
7. **Non-blocking and queued.** The tool returns an "accepted, queued"
   result immediately. Calls queue; a new call does not interrupt the one
   being spoken.

## Open questions resolved (owner, 2026-09-30)

1. **Provenance: model search + Journal UI, no automatic retrieval.** A new
   `ProvenanceSourceKind.EXTERNAL_CANVAS` with eligibility
   `{MODEL_SEARCH, JOURNAL_UI}`. `search_history` shows it labeled as an
   external answer with the caller named, never as Jarvis's own turn. It
   never enters the automatic-retrieval feed. The spoken derivative stays
   locator-only exactly as today.
2. **Sessions: one journal session per `--mcp-mode` run.** The caller's MCP
   `clientInfo` (name, version) and transport session id go into each event's
   metadata. `JournalRecorder` keeps its single current session.
3. **Pointers live in the canvas text.** The tool signature does not change.
   The tool description asks the caller to keep headings and `file:line`
   references in the canvas; the voice-guide prompt tells the model to name
   them aloud as landmarks.
4. **Claude Code `Stop` hook: out of v2.0.** v2.0 is the explicit tool call
   only. The hook is a follow-up (it needs a CLI client for the server and a
   decision about noise from short answers).

## Design decisions (proposed here, confirmed by card approval)

- **Journal shape: one assistant-role event per call, distinct source.** The
  external canvas is recorded as `role="assistant"`, `source="mcp_canvas"`,
  `event.text` = canvas. Reason: replay (`audio/replay.py`), the
  derivative locator index, and Journal rendering already key on the
  assistant role, so they work unchanged. Identity as "not Jarvis's own claim"
  comes from the source through the provenance descriptor, and every consumer
  that treats an assistant event as Jarvis's own words must read it there.
  Known consumers of that kind, which task 2 must cover: automatic retrieval
  (`history/automatic_retrieval.py`), semantic passages
  (`journal/semantic.py`), fork seed (`journal/fork.py` copies
  `event.role` into the seed - a fork of an MCP session would otherwise make
  Claude's text the local model's own past answer), and
  `tools/history.py` serialization. The alternative, a fourth journal role
  `external`, is honest by construction but touches event validation, the
  corpus role guards, the history tool schema, and every UI renderer; it is
  the fallback if task 2's inventory shows the source-based identity cannot
  be enforced at one chokepoint (see Stop conditions).
- **Derived layers inherit the exclusion.** An annotation targeting an
  `mcp_canvas` event is not eligible for automatic retrieval either.
  Otherwise the external text reaches the auto-retrieval feed one hop
  removed. Refined while writing task 2: automatic retrieval already skips
  `mcp_canvas` events, but only through its `sources=("text",)` default,
  and annotations bypass that filter by design. Task 2 therefore adds an
  `EXTERNAL_ANNOTATION` kind and enforces eligibility at one chokepoint,
  `select_automatic_retrieval_passages()`. A fork excludes `mcp_canvas`
  events through the existing `_is_excluded_event()` mechanism.
- **What goes into metadata.** `guidance`, caller identity, and how the
  speech was produced: `derivative` (Jarvis's second pass), `verbatim`
  (canvas spoken as is), or `caller` (`spoken_text`). The caller's
  `spoken_text` is stored as the spoken derivative with origin `caller`, so
  the locator index and replay treat it like any derivative. Verbatim speech
  stores no derivative (it would duplicate the canonical text in the locator
  index).
- **Write timing mirrors mode 3.** One event per call, written when the item
  finishes: spoken, interrupted, skipped, or failed, with the matching
  status (`spoken`, `muted`, `interrupted`, `skipped`, `failed`) in
  metadata, not in `outcome`. An orderly shutdown (the service's `close()`) journals every
  accepted request exactly once: the in-flight one by what actually happened
  to it (interrupted, or spoken if its playback had already finished), the
  rest skipped; after that the service rejects new requests as closed
  (refined during task 3). Only a crash loses canvases, the in-flight one
  included; a worker that ends without `close()` (cancelled from outside, or
  killed by a bug in the middle of an item) is a crash too (task 3). This is
  accepted and documented, because the journal is append-only and an early
  write would need a second event per call.
- **The voice-guide pass is its own generation profile.** A new
  `voice_guide` profile beside `spoken_derivative` (`core/config.py`,
  `_NON_DIALOG_PROFILES`), reasoning off, with its own prompt file. The
  existing derivative prompt talks about "your own answer on screen"; the
  guide speaks about another assistant's answer that the user sees in a
  different window. `guidance` is appended as a separate prompt section.
- **The voice-guide pass has no tools.** Canvas text is untrusted input to
  the local model. With no tools, a prompt injection in it can at worst
  change what is spoken. `McpHost` stays `OFF` for the whole `--mcp-mode`
  run.
- **The voice guide runs outside the user-turn lifecycle.** (Refined while
  writing task 3; the approved text said the whole derivative pass would be
  extracted and shared.) `Orchestrator.run_derivative_pass()` dispatches
  through `OllamaBackend.chat()`, whose bus events drive the turn machinery
  (`claim_turn_end()`, history, `finish_turn()`), so the dispatch half cannot
  be shared. The guide pass instead uses the bus-free `iter_chat()` (as the
  voice-intent probe and the annotation backend already do). Speech goes
  through the app's `ReplayPlayer`, which already handles mute, the shared
  playback lock, and interrupt. Mode 3 shares only the pure message
  composition and stays byte-identical. Cost: the guide is generated in full
  before it is spoken (no sentence streaming). Streaming is a follow-up if the
  delay is felt.
- **Interrupt clears the queue.** The existing interrupt hotkey
  (`HotkeySettings.interrupt`, default `ctrl+alt+i`, `core/config.py`) stops
  the item being spoken and drops the pending ones. Each is journaled with
  its outcome, and replay can speak any of them later. Rationale: pressing
  interrupt means "be quiet now", and draining a queue of stale answers would
  defeat it.
- **Limits are typed errors, not silent truncation.** A configured maximum
  canvas length and a queue cap. A call over either limit gets a typed tool
  error and is not journaled.
- **Server, port, token.** `mcp` (already in `requirements.txt`) provides the
  streamable-HTTP server. It runs inside Jarvis's event loop, bound to
  `127.0.0.1`, on a fixed configured port (config section `[mcp_mode]`; the
  `McpServerSettings` name is taken by the client side) (the client stores the URL, so the
  port cannot be ephemeral), with the SDK's host/origin validation on. The
  bearer token is generated once (`secrets.token_urlsafe(32)`) into a token
  file on first `--mcp-mode` start and reused across runs, so client config
  survives restarts; deleting the file rotates it. The token is never logged
  and never shown in the Status Console. The token is checked by a small
  ASGI middleware in front of the SDK app, not the SDK's `token_verifier`,
  which requires OAuth resource-server settings a static local token does
  not need. Any package imported directly
  (for example `uvicorn`, `starlette`) is added to `requirements.txt`
  explicitly, not relied on transitively.
- **Single-instance guard: a Windows named mutex** in the `Local\`
  namespace, taken in `main()` before anything else starts, in both modes.
  The OS releases it on process death, so a crash never leaves a stale lock
  the way a lock file can.

## Boundaries (explicitly out of scope)

- Jarvis calling any external model (rejected, roadmap).
- The Claude Code `Stop` hook (resolved question 4).
- A structured `pointers` argument or any other change to the tool signature.
- Tools for the local model in `--mcp-mode`; file operations and execution
  (parked in the roadmap).
- Multiple concurrent journal sessions, or one session per caller.
- Switching between normal mode and `--mcp-mode` without a restart.
- Showing the canvas in the Status Console as a live dialog. The user reads
  it in the caller's window; Jarvis shows it in the Journal.
- Changes to mode 1/2/3 behavior, except the behavior-preserving extraction
  of the derivative pass.

## Task-card sequence

1. **Single-instance guard.** (Size: S.) Named-mutex guard taken first in
   `main()` (`app.py`) for every start mode. A second start exits with a
   clear message and a non-zero exit code. Logic tested through an injectable
   acquirer; the real two-process refusal is a human-run check. Boundary: no
   inter-process messaging, no "focus the running instance".

2. **External canvas provenance and journal shape.** (Size: M.)
   `ProvenanceSourceKind.EXTERNAL_CANVAS` with `{MODEL_SEARCH, JOURNAL_UI}`
   in `journal/provenance.py`; the `source="mcp_canvas"` mapping; a recorder
   method for one voice-guide event with the metadata above. Inventory every
   consumer that reads an assistant event as Jarvis's own claim (list in
   design decisions) and route it through the descriptor: excluded from
   automatic retrieval (both lexical and semantic legs), annotations of such
   events inherit the exclusion, `search_history` labels it with the caller,
   and a fork either labels it or refuses to seed it (the card picks one and
   records why). Pure logic, fully unit-tested. Boundary: no queue, no
   server, no prompt.

3. **Voice-guide pipeline.** (Size: M-L.) Extract the pure message
   composition from `Orchestrator.run_derivative_pass()` (mode-3 tests
   unchanged and green). Build `VoiceGuideService` outside the turn
   lifecycle: `iter_chat()` for the guide pass, the app's `ReplayPlayer` for
   speech. Add the `voice_guide` profile and prompt, the three speech origins
   (derivative / verbatim / caller), the bounded queue with one worker, the
   interrupt-clears-queue behavior, and journaling through task 2's recorder
   method. Tested with a fake backend and fake TTS. Boundary: no MCP server,
   no CLI flag.

4. **`--mcp-mode` composition.** (Size: M.) The `--mcp-mode` flag in
   `parse_args()` (`app.py`), combinable with `--status-console`. A config
   section for the mode: port, token file, speech origin for canvas-only
   calls, max canvas length, queue cap. The mode opens no microphone input
   stream and binds only the interrupt and shutdown hotkeys -
   the card lists every `HotkeySettings` field and says bound or not.
   `McpHost` stays `OFF`. The Status Console shows the mode and disables its
   input surfaces. Boundary: the server is a stub the card's tests
   substitute.

5. **MCP server and the `speak` tool.** (Size: M.) Streamable-HTTP server on
   `127.0.0.1:<configured port>`, bearer-token check, host/origin validation,
   the token file lifecycle. `speak` with its input schema, tool
   description (including the pointer guidance from resolved question 3),
   the immediate "accepted, queued" result (with queue position), and typed
   errors for over-length canvas and a full queue. Starts and stops with
   the app lifecycle. Server status is published on the bus for the Status
   Console. Tested in-process with the SDK client over a real localhost
   socket (no network beyond loopback, CI-safe) and a fake pipeline.
   Boundary: no second tool.

6. **Journal and Status Console surfaces.** (Size: S-M.) Journal feed renders
   `mcp_canvas` events with the caller label and the speech origin; Journal
   search, annotations, and replay work on them; hidden mode suppresses them
   like any event. The Status Console shows server state (listening / port /
   queue length), not the token. Boundary: no new Journal features.

7. **Refactoring and optimization sweep.** (Size: S-M.) Behavior-preserving
   consolidation of this story's code and tests: remove extraction shims from
   task 3, collapse duplicated fixtures, confirm no provenance signal is
   expressed two ways. Boundary: this story's code only.

8. **Docs and release verification.** (Size: S.) `PROJECT.md`: an
   architecture section for v2.0, and the runtime locality contract amended
   to name the inbound localhost MCP server. User-facing setup note: the
   exact `claude mcp add --transport http ...` command with the token header,
   and where the token file is. A human-run handoff per the Testing protocol:
   second-start refusal, a real Claude Code `speak` call in each of the three
   speech origins, a queued second call, interrupt clearing the queue, then
   the call found by Journal search and replayed. Gates:
   `python -m pytest`, `ruff check`, `ruff format --check`, and
   `tools/check_handoff_self_sufficiency.py` on the handoff.

## Acceptance criteria

- [ ] A second Jarvis start, in either mode, is refused while one is running.
      (Task 1.)
- [ ] An `mcp_canvas` event maps to `EXTERNAL_CANVAS` with
      `{MODEL_SEARCH, JOURNAL_UI}`. It and annotations of it never reach
      automatic retrieval (lexical or semantic). `search_history` labels it as
      an external answer with the caller. A fork never presents it as the
      local model's own answer. (Task 2.)
- [ ] Mode 3 behaves identically after the derivative-pass extraction; its
      existing tests pass unchanged. (Task 3.)
- [ ] Queued `speak` items are spoken in order, one at a time. A new call
      never interrupts the current one. Interrupt stops the current item and
      drops the queue, and every item is journaled with its outcome.
      (Task 3.)
- [ ] In `--mcp-mode` no microphone stream is opened (the input object stays
      inert; owner, 2026-10-02), no input hotkey is bound,
      and `McpHost` stays `OFF`. (Task 4.)
- [ ] `speak` is reachable only on `127.0.0.1` with the token. It returns
      "accepted, queued" without waiting for speech, and rejects over-length
      canvases and a full queue with typed errors. (Task 5.)
- [ ] `mcp_canvas` events are visible, searchable, annotatable, and
      replayable in the Journal, with the caller named. (Task 6.)
- [ ] The sweep leaves the suite green with no acceptance-criterion
      regression. (Task 7.)
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green.
      The Claude Code end-to-end check is a prepared, self-sufficient
      human-run handoff. `PROJECT.md` records the v2.0 architecture and the
      amended locality contract. (Task 8.)

## Stop conditions

- Stop if excluding `EXTERNAL_CANVAS` from automatic retrieval cannot be
  enforced at one chokepoint (`select_automatic_retrieval_passages()`) that
  covers the lexical, semantic, and annotation legs, and needs a filter at
  each call site. That is the signal to switch to
  a fourth journal role, an architectural change to confirm (0.3, 0.4).
- Stop if distinguishing the source needs new persisted corpus data (a
  `history_corpus.db` schema bump). The FTS table already stores `source`;
  if that is not enough, the migration is scope to confirm.
- Stop if the message composition cannot be extracted without changing
  mode-3 behavior or its tests, or if the guide pass turns out to need the
  `Orchestrator`'s turn state - that is a shape problem, not an adaptation.
- Stop if the `mcp` SDK's streamable-HTTP server cannot run inside Jarvis's
  existing event loop (for example it needs its own thread or process). The
  threading model is an architectural choice to raise, not absorb.
- Stop if a bearer-token check in front of the SDK app or host/origin
  validation is not possible without forking or patching the SDK.
- Stop if Claude Code cannot send the token header to a streamable-HTTP
  server, which would leave the auth design without a client.
