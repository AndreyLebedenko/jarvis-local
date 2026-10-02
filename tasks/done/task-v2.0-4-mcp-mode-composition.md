# Task v2.0-4: `--mcp-mode` composition

**Status:** Completed. (2026-10-02; see completion notes below.)
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Depends on:** task-v2.0-1 (the guard wraps every start mode) and
task-v2.0-3 (`VoiceGuideService` to compose).
**Executor:** the story's executor profile. This card assembles a run mode
from existing parts: which inputs exist, which hotkeys are bound, which
controls are refused, and where the voice-guide worker runs. It builds no
server; the server slot is a stub (task 5). If you find yourself writing HTTP
or MCP code, or changing how a mode-1/2/3 turn works, you have left this
card - stop.

## Summary

Add the `--mcp-mode` start flag and an `[mcp_mode]` config section. In this
mode:

- no microphone stream is opened;
- no input or dialog-setting hotkey is bound;
- every control-plane action that submits input or changes dialog settings
  is refused at one policy object;
- `McpHost` stays `OFF`;
- the `VoiceGuideService` worker runs, and the interrupt hotkey clears its
  queue.

## Why this exists

Settled constraint 2 (owner): in `--mcp-mode` Jarvis accepts no user input
into the model. The mode must say so structurally. A mode that merely does
not render a chat box, while its hotkeys and endpoints still submit turns,
would not meet the constraint.

## Owner decisions before implementation (2026-10-02)

From the pre-implementation audit against the code:

1. Journal replay controls bind to the Journal's own run. Stop, Pause, and
   Resume act on the `ReplayRun` the Journal started (held in one app-level
   slot, since Stop/Pause/Resume arrive as separate requests), never on the
   player-wide current playback. `ReplayRun` gains per-run pause/resume.
   Reason: a late Pause would freeze the guide's run indefinitely, the same
   race as Stop but worse. `NORMAL` mode is observably unchanged (every
   player run there is a Journal run).
2. Existing test fakes of `run()`, `build_app()`, and the `main()` entry
   points may be updated mechanically to accept the run-mode argument. That
   is not a change of `NORMAL` behavior; a conditional-kwarg pattern that
   exists only to keep old fakes compiling is rejected.
3. Microphone: `AudioInput` is still constructed in `MCP` mode and stays
   inert; no input stream is opened and the microphone loop is not started.
   The story's "no microphone input is built" is amended to this wording.
4. Journal Stop while the guide waits on a user replay (BUSY): Stop ends only
   the user's replay; the guide then speaks. The interrupt hotkey is the way
   to silence the guide.
5. Executor defaults, confirmed: Settings save persists `settings.mcp.enabled`,
   not `mcp_host.enabled` (otherwise an `MCP`-mode save writes
   `[mcp] enabled = false` for the next normal start);
   `set_solo_session_enabled` is refused (it changes the dialog system
   prompt); `reset_module`, `request_model_options`,
   `request_microphone_options`, DELETE of a non-active session, usage and
   media GETs, and transcript generate are allowed; touchstrip controls that
   send refused commands are disabled too; the microphone chip does not show
   a listening microphone in `MCP` mode; shutdown order is server stop, then
   `await voice_guide.close()`, then the existing sequence, with a `finally`
   safety net.
6. Informational: turning TTS off while the guide speaks journals the item in
   flight `interrupted` (an outside cancel) and later items `muted`.
7. Orb and startup signals (owner, 2026-10-02, during review): in `MCP`
   mode the orb rests in a new green "MCP waiting" state instead of
   "Ready". The `listening` sound cue (startup and after an interrupt) and
   the startup print stay unchanged: they signal "up" and "interrupt done",
   which stays true in `MCP` mode. The orb stuck on Error after an ERROR
   event (no turns end in `MCP` mode) is recorded in task 6.

## Required reading before implementing

- `src/jarvis/app.py`: `parse_args()`, `main()`, `run()` (background task
  list and hotkey listeners), `run_with_status_console()`, `build_app()`,
  `App`, `wire()`, `_on_interrupt_requested()`.
- `src/jarvis/core/config.py`: `HotkeySettings`, `Settings`, `_SECTIONS`,
  and the existing `McpSettings` / `McpServerSettings`. Those describe
  servers Jarvis connects to as a client; the new section must not reuse the
  `McpServer*` names.
- `src/jarvis/ui/status_console.py` (the API class methods listed below) and
  `src/jarvis/ui/transport.py` (route table in the server's setup,
  `/api/journal/input`, `/api/journal/context/new`,
  `/api/journal/sessions/{session_id}/fork`).
- `src/jarvis/tools/` `McpHost.enable()` / `disable()` and the Control
  Center switch path (`set_mcp_enabled`, `set_tool_enabled`).

## What to build

1. **Run mode value.** A small `RunMode` enum (`NORMAL`, `MCP`) in
   `src/jarvis/core/`, decided once in `main()` and passed into `run()` /
   `run_with_status_console()` / `build_app()`. No global state.
2. **Flag.** `--mcp-mode` in `parse_args()`. It combines with
   `--status-console`, `--no-touchstrip`, and `--debug` under their existing
   rules, so `Jarvis.cmd --mcp-mode` works (the launcher passes `%*`).
3. **Config section `[mcp_mode]`** (`McpModeSettings`, registered in
   `_SECTIONS`, documented in `config.example.toml` with the same comment
   density as `[mcp]`):
   - `port`: fixed default port; the executor picks a free unprivileged
     default and documents it. There is no host key: the bind address is
     always `127.0.0.1` (settled constraint 4);
   - `token_file`: path, resolved the same way other configured data paths
     resolve (mirror `JournalSettings`). Add the default location to
     `.gitignore`;
   - `canvas_speech`: `"derivative"` (default) | `"verbatim"`;
   - `max_canvas_chars`, `max_guidance_chars`, `max_spoken_text_chars`,
     `queue_capacity`: positive ints with validated defaults. The executor
     picks and documents them. `max_canvas_chars` must leave the guide pass
     inside the model context budget, so cite the reasoning in the config
     comment.
4. **Input policy, one place.** A `RunModePolicy` (or similar) that answers
   "is this action allowed in this run mode". It is consulted by the Status
   Console API and the transport. In `MCP` mode it refuses, with a typed
   reason the UI can show:
   - text chat submit and attachments (`/api/journal/input`);
   - new context (`reset_context`, `/api/journal/context/new`);
   - fork (`/api/journal/sessions/{session_id}/fork`);
   - `toggle_thinking`, `set_reasoning_level`, `set_response_mode`;
   - `set_mcp_enabled`, `set_tool_enabled`;
   - camera enable.

   Allowed: the TTS on/off switch, visibility mode, shutdown, Settings
   save, Journal read/search, annotations, transcripts, consolidation, memory
   files, and replay controls. The card's completion notes list every API
   method and route with its verdict. A method or route added later must not
   default to allowed silently: add a test that enumerates the API surface
   against the policy's list.
5. **Composition in `run()` for `MCP`:**
   - do not start `run_microphone_loop()`; no microphone stream is opened;
   - hotkeys: bind `shutdown` and `interrupt` only. Not bound: the ones that
     submit input (`screenshot_full`, `screenshot_region`,
     `clipboard_submit`), change dialog state (`thinking_toggle`,
     `response_mode_toggle`), or control an input that does not exist
     (`mic_sleep_toggle`). Tests list every `HotkeySettings` field with its
     verdict, so a new field forces a decision;
   - never call `McpHost.enable()`, whatever `[mcp].enabled` says;
   - call `VoiceGuideService.start()` at startup, before the server accepts
     requests, and `await voice_guide.close()` on shutdown before the
     background tasks are cancelled and before the journal is flushed;
   - `_on_interrupt_requested()` also calls `voice_guide.interrupt()` when
     the service exists. Call it BEFORE `replay_player.cancel()` (the
     handler awaits `_cancel_current_turn()` first): if an await separates a
     preceding `cancel()` from `interrupt()`, the worker can briefly start
     the next queued item before the interrupt reaches the service. With no
     await between them either order is safe (task-3 review);
   - the service owns its worker task (task 3 rewrite): `close()` is the
     orderly shutdown. It rejects new requests as closed, interrupts the item
     in flight, journals every accepted request exactly once (the queue as
     `skipped`), and awaits the worker, whether or not the worker ever ran a
     step. A worker cancelled from outside without `close()` is a crash:
     unfinished canvases may be lost, as the story accepts, so the app must
     never shut the service down that way. `run_until_shutdown()` flushes
     journal writes after gathering background tasks; `close()` must complete
     before that flush. Stop the server from accepting requests before or
     together with `close()`: requests arriving after it are rejected as
     closed;
   - `on_turn_start=replay_player.cancel` (`app.py`, the `Orchestrator`
     wiring) must not fire in `MCP` mode: with no microphone there are no
     user turns, and if it fired it would cut the guide off. Verify it with a
     test rather than assuming the mode has no turns;
   - Journal Stop during the guide's wait: while a user-started Journal
     replay plays, the guide item waits (task 3, BUSY). Pressing Stop in the
     Journal ends that replay, and the guide starts speaking at once. Decide
     whether that is acceptable in `MCP` mode or whether Stop should also
     interrupt the guide; state the decision in the completion notes;
   - Journal Stop race (owner decision, 2026-10-02, task 3 rework): the
     button keeps its name; it stops the Journal's own replay sequence, and
     the guide's speech never shows a Stop control (no `ReplayProgress` is
     published for it). The stop route calls the player-wide
     `ReplayPlayer.cancel()`, so a Stop click landing just after the user's
     replay ended can cut the guide that started in its place. Fix it here:
     the Journal Stop cancels its own `ReplayRun`, not the player;
   - the guide does not consult the `Orchestrator` busy flag (story: it runs
     outside the turn lifecycle). In `MCP` mode no live turn exists, so a
     test must pin that nothing in the mode can start one (no microphone, the
     refused input controls); otherwise the next queued item could speak over
     a live turn;
   - the server slot: an injectable server-runner coroutine, a no-op stub in
     this card, which task 5 replaces;
   - the journal: the recorder's single session is the run's session
     (resolved question 2). Nothing is written until the first request is
     journaled.
6. **Status Console minimum.** The UI state snapshot carries the run mode.
   In `MCP` mode the console shows a visible mode label and disables (not
   just hides) the refused controls, so a click cannot reach a refused
   action. Server status and the queue display belong to task 6.

## Explicitly out of scope

- The MCP server and the `speak` tool (task 5).
- Journal rendering of `mcp_canvas` events and the server-status panel
  (task 6).
- Switching run modes without a restart.
- Any change to `NORMAL` mode's behavior: every existing test stays green
  unchanged.

## Tests

- `tests/test_mcp_mode.py` (new):
  - `parse_args(["--mcp-mode"])` and its combinations;
  - `[mcp_mode]` parsing, defaults, and validation errors (or extend
    `tests/test_config.py` if that is the established home);
  - the policy's verdict for every Status Console API method and every
    transport route (the enumeration test above);
  - in `MCP` mode, `run()` with fakes starts no microphone loop, registers
    exactly the `shutdown` and `interrupt` hotkeys, never enables `McpHost`
    even with `[mcp].enabled = true`, starts the voice-guide service and the
    server stub, and on shutdown awaits `voice_guide.close()` before the
    journal flush;
  - the interrupt event calls `voice_guide.interrupt()`.
- Refused transport routes return the typed refusal in `MCP` mode
  (extend `tests/test_status_console.py` / `tests/test_journal_live_ui.py`
  where those routes are already tested).

## Acceptance criteria

- [x] `--mcp-mode` starts Jarvis with no microphone stream, only the
      `shutdown` and `interrupt` hotkeys, and `McpHost` `OFF`.
- [x] Every input-submitting or dialog-setting control is refused by one
      policy object, with tests that fail when a new control appears without
      a verdict.
- [x] The voice-guide worker runs for the whole `MCP`-mode run, and interrupt
      clears its queue.
- [x] `[mcp_mode]` is parsed, validated, and documented; its token path is
      gitignored.
- [x] `NORMAL` mode is unchanged; `python -m pytest`, `ruff check`,
      `ruff format --check` green.

## Stop conditions

- Stop if refusing an action needs checks scattered across many call sites
  instead of one policy consulted at the API/transport boundary. That is a
  shape problem to report.
- Stop if not starting the microphone loop still opens an audio input device
  somewhere in `build_app()` (for example device probing at construction).
  Report what opens it; do not patch around it.
- Stop if the Status Console cannot disable a control without a larger
  restructuring of `status_console_ui/app.js` state handling.

## Completion notes (2026-10-02)

Status stays as is until the owner's review.

- Shape:
  - `src/jarvis/core/run_mode.py`: `RunMode`, `ControlAction`, `Verdict`,
    `RefusalReason`, `ActionRefusal`, `ActionRefusedError`,
    `MCP_MODE_VERDICTS` (exhaustive, a `MappingProxyType` like the other
    tables there), `RunModePolicy`.
  - `src/jarvis/core/config.py`: `McpModeSettings` (`[mcp_mode]`),
    `_build_mcp_mode_section()`, registered in `_SECTIONS` and `Settings`.
  - `src/jarvis/ui/transport.py`: `Route` and the declarative `ROUTES` table
    (the only way an HTTP route is registered), `_guarded()` (policy, then
    the token check, then 403), `_dispatch_control()` checks the policy;
    `UiStateStore` owns the one `RunModePolicy` and the server enforces
    `state.run_mode_policy`, so snapshot and enforcement share one source,
    `control_commands()`, the `run_mode` snapshot key, `refusal_payload()` /
    `refusal_error_payload()`.
  - `src/jarvis/ui/status_console.py`: `run_mode_payload()`;
    `StatusConsoleApi(run_mode=...)` persists the configured
    `[mcp].enabled` on a Settings save in `MCP` mode.
  - `src/jarvis/audio/replay.py`: `ReplayRun.pause()` / `resume()`,
    `ReplayRunSlot`, `SequencePlayer.start_from()`.
  - `src/jarvis/app.py`: `--mcp-mode`, `main()` decides the mode,
    `App.run_mode` / `voice_guide` / `journal_replay`,
    `build_app(run_mode=...)` builds the `VoiceGuideService`,
    `_user_input_subscriptions()`, `_background_work()`,
    `_start_mcp_mode()` / `_stop_mcp_mode()` / the `finally` safety net
    (acts only when the orderly shutdown did not complete),
    `McpServerRunner` and the no-op `serve_no_mcp_server`,
    `_seed_microphone_health()`, Journal replay controls bound to
    `App.journal_replay`.
  - UI: `index.html` mode label (`runModeBadge`), `app.js` /
    `touchstrip.js` `applyRunMode()` and `isActionRefused()`, `strings.js`
    `run_mode_mcp_label` / `run_mode_mcp_hint`, `style.css` /
    `touchstrip.css` styles; `ui/text.py` `mic_detail_off_mcp_mode`.
  - Orb (owner decision 2026-10-02): `RuntimeState.MCP_WAITING`
    (`ui/contract.py`, `contract.js` `RUNTIME_STATES`), label "MCP waiting"
    / "MCP ожидает" in `ui/text.py` `_RUNTIME_STATE_TEXT` (where every orb
    label is localized; the substatus reuses `ready_to_listen`, "Waiting for
    a request" / "Ожидаю запрос"), green `--green` tokens and a
    `html[data-state="mcp_waiting"]` rule in `style.css` and
    `touchstrip.css`, a `demo.js` button. `RuntimeStateTracker` takes a
    `ready_state` (default `LISTENING`); `wire_status_console()` passes
    `MCP_WAITING` in `MCP` mode. Pinned by `tests/test_runtime_state.py`,
    `tests/test_ui_qa.py` (rule on both surfaces, green, listening still
    cyan, `contract.js` matches the enum), and
    `tests/main_split/test_main_mcp_mode.py` (after warm-up the orb is
    `MCP_WAITING` in `MCP` mode, `LISTENING` in `NORMAL`; both labels).
    `tests/test_ui_contract.py`'s exact state set gains `mcp_waiting`.
  - `config.example.toml` `[mcp_mode]`; `.gitignore` `/mcp_mode.token`;
    `PROJECT.md` v2.0 section (run mode, policy, composition, Journal-run
    slot).
- `[mcp_mode]` defaults: `port = 47821` (unprivileged, outside the usual
  dev-server ranges; validated 1024-65535), `token_file = "mcp_mode.token"`
  (CWD-relative like `[journal].root`), `canvas_speech = "derivative"`,
  `max_canvas_chars = 40000` (`num_ctx` 65536 minus the default
  `num_predict` 16384 leaves 49152 prompt tokens; the conservative estimator
  is at most one token per Cyrillic character, so 40000 + guidance + prompt
  fits for any language), `max_guidance_chars = 2000`,
  `max_spoken_text_chars = 8000` (TTS only, not context-bound),
  `queue_capacity = 8`. Only `queue_capacity` and `canvas_speech` are
  consumed in this card; the rest are for task 5.
- Policy verdicts. WebSocket control commands (every public
  `StatusConsoleApi` method except the wiring `set_loop` /
  `set_shutdown_event`):

  | Command | MCP mode |
  |---|---|
  | `toggle_thinking` | refused |
  | `set_reasoning_level` | refused |
  | `set_response_mode` | refused |
  | `set_mcp_enabled` | refused |
  | `set_tts_enabled` | allowed |
  | `set_solo_session_enabled` | refused |
  | `set_tool_enabled` (camera enable included) | refused |
  | `reset_context` | refused |
  | `reset_module` | allowed |
  | `set_visibility_mode` | allowed |
  | `request_shutdown` | allowed |
  | `request_model_options` | allowed |
  | `request_microphone_options` | allowed |
  | `save_config_selection` | allowed |

  HTTP routes (`ROUTES` in `transport.py`; the static UI files are always
  served):

  | Route | Action | MCP mode |
  |---|---|---|
  | GET `/ws` | `ui_shell` | allowed |
  | GET `/` | `ui_shell` | allowed |
  | GET `/api/journal/sessions` | `journal_read` | allowed |
  | POST `/api/journal/input` (text and attachments) | `journal_input` | refused |
  | POST `/api/journal/context/new` | `journal_new_context` | refused |
  | POST `/api/journal/sessions/{session_id}/fork` | `journal_fork` | refused |
  | GET `/api/journal/usage` | `journal_read` | allowed |
  | GET `/api/journal/sessions/{session_id}` | `journal_read` | allowed |
  | DELETE `/api/journal/sessions/{session_id}` | `journal_delete_session` | allowed (the active session is still 409) |
  | GET `/api/journal/search` | `journal_read` | allowed |
  | GET `/api/journal/transcripts/{session_id}/{event_position}` | `journal_read` | allowed |
  | PUT `/api/journal/transcripts/{session_id}/{event_position}` | `transcript_edit` | allowed |
  | POST `.../transcripts/{session_id}/{event_position}/generate` | `transcript_generate` | allowed |
  | POST `/api/journal/replies/{session_id}/{event_position}/replay` | `replay` | allowed |
  | POST `.../replies/{session_id}/{event_position}/replay-sequence` | `replay` | allowed |
  | POST `/api/journal/replies/replay/stop` | `replay` | allowed |
  | POST `/api/journal/replies/replay/pause` | `replay` | allowed |
  | POST `/api/journal/replies/replay/resume` | `replay` | allowed |
  | GET `/api/journal/annotations/{session_id}` | `journal_read` | allowed |
  | POST `/api/journal/annotations/{session_id}/generate` | `annotation_generate` | allowed |
  | GET `/api/journal/annotations/{session_id}/{annotation_id}` | `journal_read` | allowed |
  | PUT `/api/journal/annotations/{session_id}/{annotation_id}` | `annotation_edit` | allowed |
  | GET `/api/journal/consolidation/{session_id}` | `journal_read` | allowed |
  | GET `/api/journal/consolidation/{session_id}/status` | `journal_read` | allowed |
  | POST `/api/journal/consolidation/{session_id}/execute` | `consolidation_execute` | allowed |
  | GET `/api/journal/media/{session_id}/{media_path}` | `journal_read` | allowed |
  | GET `/api/memory/files/{file_id}` | `memory_file_read` | allowed |
  | PUT `/api/memory/files/{file_id}` | `memory_file_write` | allowed |

  Pinned by `tests/test_mcp_mode.py`: every action has an explicit verdict,
  the API methods equal the policy-checked commands, the server registers
  only `ROUTES` plus the static files, the full (method, path) -> action
  table above (`EXPECTED_ROUTE_ACTIONS`), and exactly the three routes above
  are refused. `tests/test_status_console.py` pins, per surface, that every
  refused action the surface can send has a disabled marking (not only a
  click guard). `tests/main_split/test_main_mcp_mode.py` composes the
  Status Console path in `MCP` mode (the server refuses input, `run()` and
  `build_app()` get `RunMode.MCP`, a Settings save keeps `[mcp] enabled`).
- Hotkeys in `MCP` mode (`HotkeySettings`, `src/jarvis/core/config.py`;
  pinned by `MCP_MODE_BINDS_HOTKEY` in
  `tests/main_split/test_main_mcp_mode.py`): bound `shutdown`, `interrupt`;
  not bound `screenshot_full`, `screenshot_region`, `clipboard_submit`
  (submit input), `thinking_toggle`, `response_mode_toggle` (dialog
  settings), `mic_sleep_toggle` (no microphone). There are no
  playback-control hotkey fields.
- Owner decisions, as implemented:
  1. Journal Stop, Pause, and Resume act on `App.journal_replay`
     (`ReplayRunSlot`), the run the Journal started last; the held-open
     replay request waits on the `ReplayRun` it started (the slot has no
     `wait()`); `ReplayRun` has per-run `pause()` / `resume()`. Player-wide
     `cancel()` stays for the interrupt handler, TTS-off, and
     `on_turn_start`.
  2. Fakes updated mechanically for the run-mode argument:
     `tests/test_single_instance.py` (`EntryPointSpy.run`, `run_probe`,
     `failing_run`, one expected launch dict),
     `tests/main_split/test_main_status_console.py` (`build_app` lambdas,
     `fake_run`, `failing_run`), `tests/main_split/test_main_debug_mode.py`
     (one `build_app` lambda). No assertion about `NORMAL` behavior changed.
  3. `AudioInput` is constructed and inert; the microphone loop is not
     started.
  4. A Journal Stop during the guide's BUSY wait ends only the user replay;
     the guide then speaks. The interrupt hotkey silences the guide.
  5. Executor defaults as listed; the touchstrip's Thinking and Reset
     context controls are disabled (class `disabled`, `aria-disabled`, and
     a guard in their handlers).
  6. TTS off while the guide speaks: the item in flight is journaled
     `interrupted`, later items `muted` (unchanged, informational).
- Judgment calls beyond the card:
  - The policy is consulted only in the transport (`_dispatch_control()`
    and the route table), not inside `StatusConsoleApi` too: every API
    control reaches the engine through `_dispatch_control()` (the native
    window close calls only `request_shutdown`, always allowed), so a
    second check would gate the same thing twice. Accepted in the audit.
  - `wire()` subscribes no user-input event in `MCP` mode. This makes "no
    turn can start" structural rather than relying on publishers being
    absent, and is what the `on_turn_start` test pins.
  - Per-route guard at registration instead of an aiohttp middleware: same
    single seam, and a route cannot exist without an action.
  - `_run_reply_replay()` / `_run_reply_sequence()` now hold the request
    open on the run they started (`_start_reply_replay()` /
    `_start_reply_sequence()` return the `ReplayRun`; the public
    `replay_reply()` / `replay_sequence()` still return `ReplayOutcome`)
    instead of the player-wide `wait_for_pending()`; identical in `NORMAL`
    mode.
  - Refused-route tests extend `tests/test_ui_transport.py`, where those
    routes are tested today (the card named `test_status_console.py` /
    `test_journal_live_ui.py`).
- Open for later tasks, not decided here: the startup `listening` cue
  still plays in `MCP` mode (owner to decide); while the voice guide speaks
  the orb stays `MCP_WAITING` (the guide publishes no turn events);
  server status and queue display are task 6.
  The server runner's signature (`McpModeSettings`, `VoiceGuideService`) is
  a starting point that task 5 may widen.

### Manual handoff (human-run)

Run from the project folder (`D:\AI\Jarvis`). Close any running Jarvis first:
a second instance is refused.

Hotkeys are named below by their `HotkeySettings` field
(`src/jarvis/core/config.py`) with the default from that class. The
`[hotkeys]` table in `config.toml` uses the same key names, and
`config.example.toml` lists them; if your `config.toml` sets a key, press
your value instead of the default.

| `[hotkeys]` key | Default | Bound in MCP mode |
| --- | --- | --- |
| `shutdown` | Ctrl+Alt+Q (`"ctrl+alt+q"`) | yes |
| `interrupt` | Ctrl+Alt+I (`"ctrl+alt+i"`) | yes |
| `screenshot_full` | Ctrl+Alt+S (`"ctrl+alt+s"`) | no |
| `screenshot_region` | Ctrl+Alt+R (`"ctrl+alt+r"`) | no |
| `mic_sleep_toggle` | Ctrl+Alt+M (`"ctrl+alt+m"`) | no |
| `clipboard_submit` | Ctrl+Alt+V (`"ctrl+alt+v"`) | no |
| `thinking_toggle` | Ctrl+Alt+T (`"ctrl+alt+t"`) | no |
| `response_mode_toggle` | Ctrl+Alt+O (`"ctrl+alt+o"`) | no |

1. MCP mode, console. Run `Jarvis.cmd --mcp-mode` (the launcher adds
   `--status-console`). Expected: the header shows the violet "MCP MODE"
   label; after warm-up the orb is green and reads "MCP waiting" with
   "Waiting for a request" under it ("MCP ожидает" / "Ожидаю запрос" when
   `config.toml` or `config.ui.toml` sets `[ui] language = "ru"`; default
   `"en"`, `UiSettings` in `src/jarvis/core/config.py`), on the console and
   on the touchstrip; the Microphone module reads "off in MCP mode"; the
   Windows
   microphone-in-use indicator (the microphone icon in the taskbar tray)
   never appears.
2. Refused controls are disabled, not hidden, and clicking them does
   nothing: the Thinking level buttons (Off / Low / Medium / High), the
   Response mode buttons (Text / Voice / Text+voice), the MCP Enable button,
   every tool checkbox (camera included), the Journal "New context" button,
   the Journal solo checkbox, the "Continue" button on a past Journal
   session and "Continue" in that session's context menu. The Journal input
   box is not shown at all yet: with no request journaled there is no active
   session, so the existing "not the active session" note replaces it (its
   disabled state becomes visible once task 5 journals a request; the
   engine refuses input either way). On the touchstrip, open the Actions page:
   Thinking and Reset context are greyed and do not react. Allowed controls
   still work: TTS on/off, Open/Hidden, Settings Apply, Journal search, Play
   on a past reply.
3. Hotkeys. Press the hotkey of each key marked "no" in the table:
   `screenshot_full`, `screenshot_region`, `mic_sleep_toggle`,
   `clipboard_submit`, `thinking_toggle`, `response_mode_toggle`. Expected:
   no Jarvis cue and no new line in the events panel (they are not
   registered in this mode). Press the `interrupt` hotkey: no error (nothing
   to interrupt yet; the guide receives requests only after task 5).
4. Shutdown. Press the `shutdown` hotkey. Expected: the process exits. In
   `logs\jarvis.log` (directory `[logging].directory`, default `"logs"`,
   `LoggingSettings` in `src/jarvis/core/config.py`) the last run shows, in
   order, "Shutdown: stopping the MCP server", "Shutdown: closing the voice
   guide", "Shutdown: flushing pending journal writes", and last
   "Shutdown: teardown complete". Neither of the first two lines appears
   again after "Shutdown: teardown complete".
5. MCP stays off with `[mcp] enabled = true`. Open `config.ui.toml` in the
   project folder (create it if absent) and set, under an `[mcp]` table,
   `enabled = true` (add the table if absent; this file overrides
   `config.toml`). Run `Jarvis.cmd --mcp-mode`. Expected: the MCP card reads
   "Off" and no MCP server process starts. Open Settings, press Apply, shut
   down with the `shutdown` hotkey, and reopen `config.ui.toml`: its `[mcp]` table
   still reads `enabled = true`. Restore the `[mcp]` value you had before
   step 5.
6. Normal mode is unchanged. Run `Jarvis.cmd`. Expected: no "MCP MODE"
   label, after warm-up the orb is cyan and reads "Ready" ("Готов" in
   Russian), the Microphone module listens, all controls above are enabled.
   Every hotkey in the table works as before: `screenshot_full` and
   `screenshot_region` capture the screen, `mic_sleep_toggle` sleeps and
   wakes the microphone, `clipboard_submit` sends the clipboard text,
   `thinking_toggle` changes the Thinking level, `response_mode_toggle`
   cycles the Response mode, `interrupt` stops a reply being spoken. Play a
   past reply in the Journal, then Pause, Resume, and Stop it: each acts on
   that replay as before. Shut down with the `shutdown` hotkey.

Not checkable until task 5 (the server stub accepts nothing): a real guide
speaking, interrupt clearing its queue, and the late-Stop race against the
guide's speech. They are covered by automated tests here and belong to the
task-8 handoff.

### Closure (2026-10-02)

- Manual handoff above: passed (owner, 2026-10-02).
- After an external review, two hardening fixes: the held Journal request
  waits on the `ReplayRun` it started (`ReplayRunSlot.wait()` removed), and
  the verdict tables in `src/jarvis/core/run_mode.py` are read-only
  (`MappingProxyType`).
- Final gates: 3147 passed, 1 skipped; `ruff check` and
  `ruff format --check` green.
