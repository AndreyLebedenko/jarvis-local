# Task v1.5.2-1: Text input endpoint and turn source

**Status:** Completed.
**Story:** `tasks/done/story-v1.5.2-journal-ux-pack.md`
**Depends on:** nothing new; builds on the existing transport and
`_start_turn()` path.

## Summary

Add an authenticated local HTTP endpoint that accepts a typed user
message from the Journal input dock and starts a normal Jarvis turn
through the shared orchestrator path. Transport and orchestrator only;
no UI changes in this task.

## Context you need

- `src/jarvis/ui/transport.py`: `UiTransportServer.start()` route table,
  `_require_http_token()`, `_is_hidden()`, and the journal GET handlers -
  the new endpoint must reuse exactly this auth and Hidden gating.
- `src/jarvis/app.py`: `Orchestrator.on_clipboard()` and
  `_start_turn()` - the typed turn mirrors the clipboard turn shape
  (real text into `ConversationHistory`, no pending screenshot
  attachment, busy-guard rejection).
- `src/jarvis/journal/recorder.py`: `record_text_user(text, source=...)`
  already supports a source label.
- `tasks/task-v1.6.0-7-journal-upload-api.md`: the future consumer of
  this submit path; do not preclude a multipart extension of the same
  route.

## Boundary

- One endpoint, working name `POST /api/journal/input`, JSON body
  `{"text": "..."}`. No file upload, no STT, no session continuation.
- No JavaScript changes beyond what existing tests require; the dock UI
  is task-v1.5.2-2.
- Do not change voice or clipboard turn behavior.

## Requirements

- Token-authenticated POST endpoint accepting a typed message; invalid
  or missing token behaves exactly like the existing journal endpoints.
- The transport owns auth and the Hidden gate: in Hidden mode the
  submission is rejected the same way journal GET endpoints are
  suppressed, before the payload reaches the orchestrator - the
  orchestrator (and therefore the engine) never receives the text and
  has no Hidden-related result value.
- Empty/whitespace-only text is rejected with a structured error.
- Enforce a max text length with a structured over-limit rejection
  (decided at story review, 2026-07-19): typed input is rejected, not
  truncated, because the UI can keep the text and ask the user to
  shorten it. Truncation-with-marker remains the semantics for
  clipboard/file text, where the source is external - do not unify the
  two.
- The orchestrator gains an explicit text-submission entry point that
  returns a structured accepted/rejected result with a machine-readable
  reason (accepted, busy, empty, over-limit); for requests that pass
  the transport's auth and Hidden gate, the transport handler only maps
  that result onto the HTTP response. The transport must not inspect
  busy state itself - the orchestrator's busy-guard stays the single
  authority.
- An accepted message starts a turn through `_start_turn()`, records the
  real text in `ConversationHistory`, and reaches the journal through
  `record_text_user()` with a source label distinguishing dock input
  from clipboard if the existing labels would otherwise collide.
- Response contract is JSON and returns accepted/rejected state with a
  machine-readable reason.

## Acceptance criteria

- [x] Transport tests cover authorized submission, missing/invalid
      token, Hidden rejection, empty text, over-limit text, and busy
      rejection.
- [x] A transport test proves a Hidden-mode submission does not call
      the orchestrator entry point at all (the text never leaves the
      transport layer).
- [x] An orchestrator-level test proves the typed turn goes through the
      shared `_start_turn()` path and never attaches a pending
      screenshot.
- [x] Orchestrator-level tests pin the structured accepted/rejected
      result (accepted, busy, empty, over-limit) independently of the
      HTTP layer, and a transport test proves the handler maps that
      result without reading orchestrator busy state directly.
- [x] No UI behavior changes.
- [x] `python -m pytest` and Ruff checks are green.
