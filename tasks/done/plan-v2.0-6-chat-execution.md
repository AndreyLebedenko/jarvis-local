# Plan: task v2.0-6 executed through the Quoroom chat

**Status:** Completed. (2026-10-03)
**Card:** `tasks/task-v2.0-6-journal-and-console-surfaces.md`.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Branch:** `feat/v2.0-6-journal-and-console-surfaces` from `main` (`fe9ba16`).

## Roles

- **Orchestrator (`claude-code`).** Owns the card boundary, slice order,
  open decisions, stop conditions, and the acceptance checklist. Reviews each
  slice (diff + gate output), with read-only subagents for review or
  research. Commits only after the owner's review.
- **Implementer (`glm`).** Writes code and tests, TDD, one slice at a time,
  in this working tree on this branch. Does not commit, merge, or switch
  branches. Reports each slice in the chat (multi-line reports by
  `--file`).
- **Owner (human).** Decides open questions; approves the final result.

## Slice protocol

1. The implementer reads the card's "Required reading" before slice 1.
2. One slice at a time. Do not start the next slice until the orchestrator
   says "go" for it in the chat.
3. A slice report contains: changed files, new/changed tests, the output tail
   of the three gates, and any deviation from the card or this plan.
4. Gates for every slice: `python -m pytest`, `ruff check`,
   `ruff format --check` (all three, every time).
5. Verify, do not assume: when the card says "verify with a test", write the
   test first and change code only if it fails.

## Slices

- **S1. Feed and search labeling (card items 1, 2).** Payload carries
  `source`, `caller`, `speech_origin`, `speech_status` for `mcp_canvas`
  events (first check what the feed payload already carries; reuse it). A
  normal assistant event payload is unchanged (test). `app.js` renders the
  external-answer label, the existing collapsed "spoken aloud" block for
  `derivative`/`caller`, and a status note for non-`spoken` statuses. Same
  label in canonical search results. Derivative locator group: a test only.
- **S2. Annotations and replay verification (card item 3).** Transport
  boundary tests: annotation generate/edit on an `--mcp-mode` session;
  replay of an `mcp_canvas` event speaks the stored derivative, or the
  canvas for `verbatim`. Code changes only if a test shows a gap; a gap
  rooted in task 2's event shape is a stop (card stop condition 2).
- **S3. Server and queue block, hidden mode (card items 4, 5).** A typed
  state block pushed on `McpServerStatusChanged`
  (`src/jarvis/mcp_mode/server.py`) and `VoiceGuideQueueChanged`
  (`src/jarvis/dialog/voice_guide.py`), mirroring the `set_mcp_state()`
  pattern in `src/jarvis/ui/transport.py`. Rendered on the Status tab only in
  `MCP` run mode. Sentinel-token test over every pushed payload. Hidden mode
  through `src/jarvis/ui/visibility.py`, no new check.
- **S4. Orb in `MCP` mode (card item 6).** Decided by the owner
  (2026-10-03):
  - Error clears on the next `VoiceGuideQueueChanged` (a request accepted
    or an item finished). A server that never came up sends none, so Error
    stays, which is honest.
  - A failed guide item keeps today's behavior: an error sound cue only, the
    orb does not go to Error.
  - The orb follows the guide in phases: THINKING while the local model
    generates the guide, SPEAKING while playback runs, MCP_WAITING when the
    queue is empty. `verbatim` and `caller` items have no generation phase.
  - Allowed exception to the boundary below: `VoiceGuideQueueChanged` gains
    an additive phase field, and the service publishes one extra queue event
    when playback starts. Existing task-3 tests stay green unchanged except
    where they assert the exact event shape.
  - The tracker change goes through `RuntimeStateTracker`
    (`src/jarvis/ui/runtime_state.py`), the single owner of orb state; new
    substatus keys get `en` and `ru` text.

## Boundaries (escalate instead of crossing)

- No new Journal view, filter, or endpoint; payload fields only.
- Normal assistant rows: only a branch on the event's source, nothing else.
- Do not change `src/jarvis/dialog/voice_guide.py`,
  `src/jarvis/mcp_mode/*`, or `src/jarvis/journal/*` without asking first.
- No token and no token-file path in any payload, log, or UI string.
- Every new UI string gets `en` and `ru` entries (`src/jarvis/ui/text.py`,
  and `status_console_ui/strings.js` for JS-side strings).
- CLAUDE.md section 0 stop conditions apply as written, especially 0.7
  (same fix twice) and 0.9 (environment errors).
- WebView visual review is human-run (task 8 handoff); do not treat its
  absence as a gap. CLAUDE.md tooling note 7 applies if you use the Browser
  pane.
