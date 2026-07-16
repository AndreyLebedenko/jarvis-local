# Task journal-04: Journal API on the console transport

**Status:** Planned.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`
**Depends on:** task-journal-01, -02, -03.

## Summary

Expose the journal to the Status Console UI through the existing local
HTTP+WebSocket transport: list sessions, fetch a session feed, search,
serve media files, and push a live event when a new turn is journaled.

## Context you need

- `src/jarvis/ui/transport.py`: the aiohttp HTTP+WS transport, including
  how existing payload builders from `src/jarvis/ui/status_console.py`
  are shaped and how WS messages are typed/versioned
  (PROTOCOL_VERSION). Follow the existing handshake/auth pattern exactly
  - do not invent a second mechanism.
- `src/jarvis/ui/contract.py`: how UI-facing shapes are defined; add
  journal shapes in the same style.
- `tests/` contains existing transport tests - mirror their approach
  (aiohttp test client, no real browser).
- Story card: this task resolves the story's open point "how the WebView
  plays journal audio from disk" - answer: serve media over the existing
  local HTTP transport, never file://.

## Boundary

- Changes limited to: `src/jarvis/ui/contract.py`,
  `src/jarvis/ui/transport.py`, `src/jarvis/ui/status_console.py` (payload
  builders), journal package (only if a thin read API is missing), tests.
- No JS/HTML changes (task-journal-05).
- Read-only API: no endpoint may mutate the journal.
- Media serving must be restricted to files inside the journal root
  (reject path traversal), local transport only, same auth as the rest
  of the console.

## Requirements

- HTTP endpoints (same auth/prefix conventions as existing ones):
  - list sessions (id, start/end timestamps, title = first meaningful
    user text or a placeholder for voice-only starts);
  - get session feed (ordered events, media as URLs to the media
    endpoint, transcript field passed through even though it is None);
  - search (query + optional date range, returns hits linking back to
    session + position);
  - get media file (correct Content-Type for wav/png/jpg).
- WS push: a `journal_event` message when the recorder appends an event
  for the current session, so the open Journal view appends live. Reuse
  the channel that already pushes SystemEvent-type messages.
- Hidden mode: while VisibilityMode is Hidden, journal HTTP endpoints
  return a neutral "hidden" response and `journal_event` pushes are
  suppressed - content must not reach the UI process at all, mirroring
  how the vision chip detail is blanked.

## Acceptance criteria

- [ ] Transport tests cover: session list, feed, search (incl. date
      filter), media serving with traversal rejection, and correct
      Content-Type.
- [ ] A test proves Hidden blocks feed/search/media responses and
      suppresses `journal_event` pushes; switching back to Open restores
      them.
- [ ] A test proves a journal append while a WS client is connected
      results in exactly one `journal_event` push with the event payload.
- [ ] `python -m pytest` green; no new dependencies.
