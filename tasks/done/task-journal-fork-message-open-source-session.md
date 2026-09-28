# Task: "Open source session" action on the fork provenance message

**Status:** Completed.
**Source:** Owner request, 2026-09-28 (commit `526c950`, branch
`feature/tts-language-mode`).

## Summary

The first message of a forked session (source `fork`, rendered with the
`FORK` badge: "Эта сессия продолжает более ранний разговор...") has a
"More actions" (`...`) menu whose only entry today is "Generate annotation".
Add an entry that navigates to the source session the fork was created from.

## Context

- The fork event carries the source id:
  `JournalRecorder.start_fork_session()` writes
  `metadata.continued_from = source_session_id`
  ([recorder.py:134-162](../../src/jarvis/journal/recorder.py)).
- Verified: event metadata already reaches the frontend in the feed payload
  (`_journalProvenanceDetail()` reads `event.metadata.seed` from the same
  event). No backend change is needed.
- The per-message menu is built by `_journalMessageMenuEntries(row)` in
  `status_console_ui/app.js`; entries appear only when the row carries the
  matching control or dataset field. Navigation is
  `selectJournalSession(sessionId)`; the known sessions are cached in
  `_journalSessions` (set by `refreshJournalSessions()`).
- The fork point is the end of the source session: `build_fork_seed()`
  seeds from the whole source session
  ([fork.py:63](../../src/jarvis/journal/fork.py:63)), and the feed render
  already scrolls to the bottom. No fork-point scrolling is needed.

## Current Boundary

- Frontend only: `app.js` (dataset field on the fork row, menu entry, a small
  navigation helper), `strings.js` (RU/EN label), source-text tests.
- Only on the fork provenance message; other messages unchanged.
- No new endpoint, no change to `selectJournalSession()` semantics.

## Acceptance Criteria

- [x] The fork message's "More actions" menu shows an "Open source session"
      entry (RU/EN strings in `strings.js`) when `metadata.continued_from`
      is present, on both full renders and live appends.
- [x] Choosing it selects the source session in the journal, same as
      clicking it in the session list, and brings its session-list row into
      view.
- [x] If the source session is not among the known sessions (deleted), the
      entry is shown disabled; it never fails silently.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` green.
- [x] Visual check of the menu is a human handoff (WebView).

## Manual Handoff (human-run: WebView, live Ollama)

Needs the journal enabled: `[journal] enabled = true` in `config.toml`
(default in `config.example.toml:424`). Step 7 deletes a session, so use a
throwaway session created in step 2, not a real conversation.

1. Start Jarvis with the console: `Jarvis.cmd` (runs
   `python -m jarvis --status-console`, see `README.md:313-316`).
2. Open the "Journal" / "Журнал" view (`strings.js` key `view_journal`). In
   the input dock type `handoff fork source` and send it. Wait for the
   reply. This creates session A.
3. Close Jarvis and start it again with `Jarvis.cmd`, so that A is no longer
   the current session.
4. In the Journal session list, pick session A (its title/time match step 2)
   and click its "Continue conversation" / "Продолжить разговор" button
   (key `journal_session_continue`). A new session F opens; its first
   message has the `FORK` badge.
5. On that fork message, click the `...` button (or right-click the
   message). Expected: the menu shows "Open source session" / "Открыть
   исходную сессию" (key `journal_fork_open_source`), enabled, above
   "Generate annotation" / "Сгенерировать аннотацию".
6. Click it. Expected: session A is selected in the list (highlighted and
   scrolled into view if the list is long), and the feed shows A's messages,
   scrolled to the bottom.
7. In the list, delete session A with its delete button and confirm. Select
   session F again and open the fork message's `...` menu. Expected: "Open
   source session" is shown but disabled; clicking it does nothing.
8. Optional: open the `...` menu on an ordinary user or assistant message.
   Expected: no "Open source session" entry.

Report: pass/fail per step 5-8, and a screenshot of the menu from step 5.
