# Task v2.0-4: `--mcp-mode` composition

**Status:** Not started.
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

- [ ] `--mcp-mode` starts Jarvis with no microphone stream, only the
      `shutdown` and `interrupt` hotkeys, and `McpHost` `OFF`.
- [ ] Every input-submitting or dialog-setting control is refused by one
      policy object, with tests that fail when a new control appears without
      a verdict.
- [ ] The voice-guide worker runs for the whole `MCP`-mode run, and interrupt
      clears its queue.
- [ ] `[mcp_mode]` is parsed, validated, and documented; its token path is
      gitignored.
- [ ] `NORMAL` mode is unchanged; `python -m pytest`, `ruff check`,
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
