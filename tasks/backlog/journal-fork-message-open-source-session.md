# Backlog: "Open source session" action on the fork provenance message

**Status:** Open. Feature request, not blocking.
**Source:** Owner request, 2026-09-28 (commit `526c950`, branch
`feature/tts-language-mode`).

## Summary

The first message of a forked session (source `fork`, rendered with the
`FORK` badge: "Эта сессия продолжает более ранний разговор...") has a
"More actions" (`...`) menu whose only entry today is "Generate annotation".
Add an entry that navigates to the source session the fork was created from.

## Context

- The fork event already carries the source id:
  `JournalRecorder.start_fork_session()` writes
  `metadata.continued_from = source_session_id`
  ([recorder.py:134-162](../../src/jarvis/journal/recorder.py)); the fork
  HTTP response carries the same key
  ([transport.py:2163-2173](../../src/jarvis/ui/transport.py)).
- The per-message menu is built by `_journalMessageMenuEntries(row)`
  ([app.js:2831](../../src/jarvis/ui/status_console_ui/app.js:2831)); entries
  appear only when the row carries the matching control or dataset field.
- Navigation already exists as `selectJournalSession(sessionId, ...)`
  ([app.js:2163](../../src/jarvis/ui/status_console_ui/app.js:2163)).
- Not verified yet: whether `continued_from` reaches the frontend in the feed
  event payload, and whether the fork row currently keeps it anywhere in the
  DOM.

## Current Boundary

- Frontend menu entry plus whatever minimal plumbing exposes
  `continued_from` to the row. No new endpoint unless the feed payload
  cannot carry it.
- Only on the fork provenance message; other messages unchanged.

## Acceptance Criteria

- [ ] The fork message's "More actions" menu shows an "Open source session"
      entry (RU/EN strings in `strings.js`) when `continued_from` is known.
- [ ] Choosing it selects the source session in the journal, same as
      clicking it in the session list.
- [ ] If the source session no longer exists (deleted) or is hidden, the
      entry is disabled or shows an explicit status message; it never fails
      silently.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.
- [ ] Visual check of the menu is a human handoff (WebView).

## Open Questions

- Nice-to-have, owner to decide: optionally scroll the source session to
  the point where the fork was taken (`selectJournalSession` already accepts
  a `contextEventPosition`), if the fork point is recoverable.
