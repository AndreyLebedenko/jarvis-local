# Task v2.0-6: Journal and Status Console surfaces

**Status:** Not started.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Depends on:** task-v2.0-2 (event shape), task-v2.0-3
(`VoiceGuideQueueChanged`), task-v2.0-4 (run mode in the UI state), and
task-v2.0-5 (server status event).
**Executor:** the story's executor profile. This card makes existing surfaces
show what the new events are. It adds no Journal feature. If you find
yourself adding a new Journal view, filter, or endpoint beyond payload
fields, you have left this card - stop.

## Summary

- The Journal feed renders `mcp_canvas` events as external answers: a caller
  label, the speech origin, and the speech status.
- Journal search, annotations, and replay work on them unchanged, which is
  verified rather than assumed.
- The Status Console shows the voice-guide server status (listening / port /
  failed) and the queue (length, speaking). The token is never shown.

## Why this exists

Settled constraint 3: journal search, memory, and annotations are preserved
in `--mcp-mode`, on the same surfaces. The user also needs to see whether the
server is up without reading logs. Without a label, an external answer in the
feed looks like Jarvis's own reply, which is exactly the confusion task 2
prevents on the model side.

## Required reading before implementing

- `src/jarvis/ui/transport.py`: journal session/feed payload builders, the
  search handler, the replay handlers, and how `set_mcp_state()` pushes a
  typed state block (the pattern for the new server/queue block).
- `src/jarvis/ui/status_console_ui/app.js` and the matching CSS: feed row
  rendering, the collapsed "spoken aloud" block (v1.9.0), the canonical vs
  locator search groups (v1.9.1 task 4), and the status tab module rows.
- `src/jarvis/ui/text.py` (UI localization: every new string gets `en` and
  `ru` entries).
- `src/jarvis/ui/visibility.py` (hidden mode must suppress the new rows and
  pushes like any journal content).
- `CLAUDE.md` tooling note 7 (Browser pane caches `file://` JS/CSS; verify
  with `fetch(url, {cache: "no-store"})` or a fresh tab).

## What to build

1. **Feed payload and rendering.** The journal event payload carries
   `source` (check whether it already does) plus the `caller` name,
   `speech_origin`, and `speech_status` from metadata. An `mcp_canvas` row
   renders:
   - a localized label such as "External answer - claude-code" instead of
     Jarvis's reply styling;
   - the existing collapsed "spoken aloud" block for `derivative` / `caller`
     origins;
   - a short status note when the status is not `spoken` (muted,
     interrupted, skipped, failed).
2. **Search.** Canonical Journal search already covers assistant-role events,
   so `mcp_canvas` hits appear. Label them the same way in results. The
   derivative locator group works for them through the v1.9.1 path
   unchanged; verify it with a test, do not re-implement it.
3. **Annotations and replay.** Verify, with tests at the transport boundary,
   that generating/editing an annotation on an `--mcp-mode` session works,
   and that replay of an `mcp_canvas` event speaks its stored derivative, or
   the canvas for `verbatim` (`assistant_reply_speech()` already does this).
   Change code only if a test shows a gap.
4. **Server and queue block.** A typed UI state block, pushed on the task-5
   server status event and the task-3 `VoiceGuideQueueChanged`: server state,
   port, failure reason, queue length, and speaking yes/no. It is rendered on
   the Status tab only in `MCP` run mode. No token and no token-file path in
   any payload.
5. **Hidden mode.** Hidden mode suppresses the new feed rows and the queue
   block's content through the existing visibility mechanism, not a new
   check.
6. **Orb state in `MCP` mode (owner, 2026-10-02, from task 4).** Task 4
   added the green `RuntimeState.MCP_WAITING` resting state
   (`RuntimeStateTracker(ready_state=...)`, `wire_status_console()`), but
   the orb returns to its resting state only at the end of a turn, and
   `MCP` mode has no turns. So an ERROR system event leaves the orb on
   Error until restart, and the guide's speech never moves the orb (the
   guide publishes only `VoiceGuideQueueChanged`). Decide and implement
   when Error clears in `MCP` mode (for example on the next queue change or
   the next item that finishes) and whether the orb shows the guide
   speaking; take the decision to the owner before implementing.

## Explicitly out of scope

- New Journal filters (for example "show only external answers").
- Showing the canvas live on the Status tab as a dialog (story boundary).
- Server controls (start/stop/rotate token) in the UI.

## Tests

- Python: payload builder tests for an `mcp_canvas` event (caller, origin,
  status present; a normal assistant event unchanged); search result labeling;
  annotation and replay round trips at the transport boundary; the server and
  queue state block pushed on each event; no payload contains the token (use
  a sentinel token value and assert its absence from every pushed payload);
  hidden-mode suppression.
- JS/UI: extend `tests/test_journal_view_ui.py` /
  `tests/test_status_console.py` in their existing style for the row label
  and the status block. The visual review of the rendered page is part of the
  task-8 human handoff (WebView visual review is human-run).

## Acceptance criteria

- [ ] An `mcp_canvas` event is visibly labeled as an external answer with its
      caller, origin, and non-`spoken` status in the feed and in search
      results.
- [ ] Journal search (canonical and heard-phrase), annotations, and replay
      work on `mcp_canvas` events, proven by tests.
- [ ] The Status tab in `MCP` mode shows server state, port, and queue; no
      payload ever contains the token.
- [ ] Hidden mode suppresses the new content.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.

## Stop conditions

- Stop if showing the caller label requires a change to how normal assistant
  rows render, beyond a branch on the event's source.
- Stop if replay or annotations fail on `mcp_canvas` events for a reason
  rooted in task 2's event shape. That goes back to task 2's contract, not a
  UI workaround.
