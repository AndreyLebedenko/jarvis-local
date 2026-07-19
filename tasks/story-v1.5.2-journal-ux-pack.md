# Story v1.5.2: Journal UX pack

**Status:** Planned, task cards pending human approval.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.5.2 section).
**Created:** 2026-07-19, to unblock `task-v1.6.0-7-journal-upload-api.md`,
which depends on the v1.5.2 text input endpoint. Owner decision
(2026-07-19): v1.5.2 and v1.5.3 are implemented on branches from current
main (which already contains the inert v1.6.0 domain tasks 1-6), not from
the v1.5.1 tag; release chronology stays 1.5.2 -> 1.5.3 -> 1.6.0.

## User-facing goal

Make the Journal view a place the user can act from, not only look at:
type a message to Jarvis from the reserved input dock, copy answers out,
see image thumbnails for what was sent to the model, and see and reclaim
the disk space the journal occupies.

## Boundaries

- No STT, no attachments, no session continuation (v1.5.3/v1.6.0 scope).
- No re-layout of the feed: the input dock and audio tiles were reserved
  for exactly these extensions.
- No automatic deletion of any journal data (cross-cutting rule 8);
  deletion is manual, per-session, confirmed by the user.
- The journal remains append-only during normal operation (cross-cutting
  rule 6). Manual per-session deletion is a user-initiated storage
  management action on whole sessions, not an edit path for events
  inside a session.
- Hidden mode remains a hard boundary: every new endpoint and control in
  this story is suppressed exactly like the existing journal endpoints.
- Runtime locality is unchanged: everything is served over the existing
  authenticated local transport; no `file://` access, no new network
  capability.

## Design decisions (proposed here, confirmed by card approval)

- **Text submission is an HTTP POST endpoint** on the existing
  authenticated transport (working name `POST /api/journal/input`), not a
  WebSocket control command. Rationale: task-v1.6.0-7 extends the same
  submit path with multipart file upload, which the JSON WS control
  channel cannot carry; building on POST avoids reworking the path one
  release later. The endpoint reuses the existing token auth and Hidden
  gating of the journal GET endpoints.
- **A typed message is a first-class turn source** entering
  `Orchestrator._start_turn()` beside voice and clipboard, recorded in
  the journal via the existing `record_text_user()` path. The layering
  is fixed (review decision 2026-07-19): the transport owns auth and
  the Hidden gate and never passes text to the orchestrator in Hidden;
  the orchestrator entry point owns the structured accepted/rejected
  result (busy, empty, over-limit), which the transport only maps -
  the busy-guard stays the single authority. Over-limit typed text
  is rejected, never truncated (review decision 2026-07-19) - the UI
  keeps the text and asks the user to shorten it; truncation-with-
  marker stays clipboard/file semantics.
- **Copy controls are UI-only**: per-answer copy button plus normal text
  selection; no transport changes.
- **Screenshot media becomes part of the journal record** (review
  finding 2026-07-19): today only voice wav bytes are recorded as media
  - the recorder gains png recording for the user turn that consumed
  the pending screenshot, mirroring the wav pattern, before any
  thumbnail rendering.
- **Thumbnails reuse the existing authenticated media transport** on
  top of that recording; rendering mirrors the audio tiles.
- **Disk usage and deletion are store-level file operations** exposed
  through new authenticated endpoints: usage reporting (total and
  per-session) and per-session deletion that also updates the
  rebuildable FTS index. The active-session guard lives in the
  transport/API layer (which knows the recorder's current session id),
  not in `JournalStore` - the store knows only files.

## Scope (ordered task cards)

- `tasks/task-v1.5.2-1-text-input-endpoint.md` - transport endpoint and
  orchestrator turn source for typed messages.
- `tasks/task-v1.5.2-2-input-dock-ui.md` - the Journal input dock UI
  wired to that endpoint.
- `tasks/task-v1.5.2-3-feed-copy-controls.md` - copy answer / copy
  selection from the feed.
- `tasks/task-v1.5.2-4-journal-screenshot-media.md` - record the
  screenshot sent to the model as journal media (recorder wiring).
- `tasks/task-v1.5.2-5-image-thumbnails.md` - image thumbnails in the
  feed for media sent to the model.
- `tasks/task-v1.5.2-6-disk-usage-and-deletion-api.md` - store and
  transport support for usage visibility and manual session deletion.
- `tasks/task-v1.5.2-7-journal-management-ui.md` - usage display and
  confirmed deletion flow in the Journal view.
- `tasks/task-v1.5.2-8-docs-and-release-verification.md` - PROJECT.md
  update, config example update if needed, and the human-run release
  checklist.

## Acceptance criteria

- [ ] A message typed in the Journal input dock reaches the model through
      the shared `_start_turn()` path, is answered aloud and in the feed,
      and is recorded in the journal like other text turns.
- [ ] Submission while busy or in Hidden mode is rejected with visible,
      non-destructive feedback (typed text is not lost).
- [ ] A whole Jarvis answer or an arbitrary selected fragment can be
      copied from the feed.
- [ ] Screenshots sent to the model are recorded as journal media and
      appear as thumbnails in the feed, served through the
      authenticated media transport.
- [ ] The Journal view shows total and per-session disk usage; a session
      can be deleted only through an explicit confirmation flow, after
      which the feed, the usage numbers, and search results are
      consistent.
- [ ] `python -m pytest` and Ruff checks are green; hardware/WebView
      verification is a prepared human-run handoff.

## Stop conditions

- Stop if the typed-turn path cannot reuse `_start_turn()` without
  changing voice/clipboard turn behavior.
- Stop if session deletion cannot keep the FTS index consistent without
  a full rebuild becoming the routine path for large journals.
- Stop if pywebview's clipboard/selection behavior blocks the copy
  controls (record findings, do not work around with external
  dependencies).
