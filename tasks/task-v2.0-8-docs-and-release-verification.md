# Task v2.0-8: Docs and release verification

**Status:** Not started.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Depends on:** tasks v2.0-1 through v2.0-7 completed and green.
**Executor:** the story's executor profile. Docs and a human-run handoff only.
No production logic change; if you need one, the story is not done - report
it instead.

## Summary

Record v2.0's settled architecture in `PROJECT.md`, amend the runtime
locality contract to name the inbound localhost MCP server, write the user
setup note, and prepare the self-sufficient human-run verification handoff
for everything that needs a live model, speakers, a second process, or a
real Claude Code client.

## Required reading before implementing

- Every completed task card of this story (their completion notes are the
  source of the settled facts).
- `PROJECT.md`: "Architecture v1.9.0", "Architecture v1.9.1", "Current
  roadmap", and the runtime locality contract (two-tier wording, revised
  2026-07-14).
- `CLAUDE.md` / `AGENTS.md` Testing protocol item 4 (handoff
  self-sufficiency) and `tools/check_handoff_self_sufficiency.py`.
- `tasks/done/task-v1.9.1-6-docs-and-release-verification.md` and
  `tasks/v1.9.1-release-verification-handoff.md` as the precedent.
- `README.md` / `README.ru.md` sections on start flags and MCP.

## What to build

1. **`PROJECT.md`:**
   - a new section "Architecture v2.0 (MCP voice guide)" with the settled
     facts: the single-instance mutex; `EXTERNAL_CANVAS` /
     `EXTERNAL_ANNOTATION` eligibility and the automatic-retrieval
     chokepoint; the journal event shape; the voice-guide pass outside the
     turn lifecycle (`iter_chat` + `ReplayPlayer`) and its no-streaming
     latency cost; the queue and interrupt semantics; the run-mode policy; the
     server's bind, token, and host-validation boundaries;
   - the runtime locality contract names the inbound, localhost-only,
     token-protected MCP server of `--mcp-mode`. Jarvis still sends nothing
     outward, and text arriving from an external model is journaled locally
     and labeled as external;
   - "Current roadmap": v2.0 marked delivered.
2. **Roadmap** (`tasks/roadmap-v1.9-v2.0.md`): v2.0 marked done, with the
   follow-ups recorded (Claude Code `Stop` hook; guide sentence streaming).
3. **User setup note** in `README.md` and `README.ru.md`:
   - how to start: `Jarvis.cmd --mcp-mode`;
   - the exact client command, with the port and token-file location cited
     from `[mcp_mode]` in `config.example.toml`:
     `claude mcp add --transport http jarvis http://127.0.0.1:<port>/mcp --header "Authorization: Bearer <token>"`.
     Replace the placeholders with how to read the actual values;
   - what the mode does not do (no microphone, no chat) and that only one
     Jarvis runs at a time.
4. **Human-run handoff** `tasks/v2.0-release-verification-handoff.md`,
   self-sufficient per Testing protocol item 4. Every hotkey, config key, and
   default is named literally with its source reference: interrupt
   `Ctrl+Alt+I` (`HotkeySettings.interrupt`, `src/jarvis/core/config.py`),
   shutdown `Ctrl+Alt+Q` (`HotkeySettings.shutdown`), and the `[mcp_mode]`
   keys. Steps must reach persistent settings state-independently (for
   example "set `[mcp_mode].canvas_speech = "verbatim"` in `config.toml`",
   not "switch to verbatim"). Checks:
   1. Single instance: with Jarvis running (either mode), a second
      `Jarvis.cmd` and a second `Jarvis.cmd --mcp-mode` are both refused with
      the message box; after closing the first, a start succeeds. Then kill
      the running Jarvis process from Task Manager and confirm the next start
      succeeds (no stale lock).
   2. Mode shape: in `--mcp-mode` the Status Console shows the mode label and
      disabled input controls; speaking into the microphone does nothing;
      `Ctrl+Alt+S` (`HotkeySettings.screenshot_full`), `Ctrl+Alt+V`
      (`clipboard_submit`), `Ctrl+Alt+T` (`thinking_toggle`), and `Ctrl+Alt+O`
      (`response_mode_toggle`) do nothing (defaults in
      `src/jarvis/core/config.py`; if `config.toml` overrides them, use the
      overridden bindings).
   3. Client setup: register the server in Claude Code with the README
      command; `/mcp` in Claude Code shows it connected with the `speak`
      tool.
   4. Origins: ask Claude Code for a long technical answer and to pass it to
      `speak`: (a) canvas only with `canvas_speech = "derivative"`: a short
      guide naming sections or files is spoken; (b) with `verbatim`: the
      canvas is read; (c) with `spoken_text`: exactly that text is spoken.
   5. Queue: two quick `speak` calls are spoken one after the other, the
      second without cutting off the first.
   6. Interrupt: during speech with one item queued, press `Ctrl+Alt+I`:
      speech stops, the queued item is not spoken, and both appear in the
      Journal as interrupted / skipped.
   7. Journal: the calls appear labeled as external answers with the caller;
      a Journal search for a canvas phrase finds them; a search for a phrase
      heard only in the guide finds the owning event in the heard-phrase
      group; replay speaks the guide again; generating an annotation for the
      session works.
   8. Normal mode afterwards: start `Jarvis.cmd` normally, ask about a topic
      covered only by an earlier external answer, and confirm the answer does
      not silently draw on it. Ask Jarvis to search its history for it, and
      confirm the result is presented as another assistant's answer.
   9. Visual review of the Journal rows and the Status tab block in both UI
      languages.

   Record the automated gate results (`python -m pytest`, `ruff check`,
   `ruff format --check` counts) at the top of the handoff.
5. **Gates:** `python tools/check_handoff_self_sufficiency.py
   tasks/v2.0-release-verification-handoff.md` passes.

## Explicitly out of scope

- Any production code change.
- Running the hardware/live steps yourself (Testing protocol item 1): hand
  them over and wait for the owner's report.

## Acceptance criteria

- [ ] `PROJECT.md` records the v2.0 architecture and the amended locality
      contract; the roadmap marks v2.0 done with its follow-ups.
- [ ] Both READMEs describe setup and limits of `--mcp-mode` with the exact
      client command.
- [ ] The handoff is self-sufficient and passes
      `tools/check_handoff_self_sufficiency.py`; automated gates are green
      and recorded in it.
- [ ] The owner executed the handoff and reported green (story completion
      gate).
