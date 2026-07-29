# Task: Journal live feed stays stale when the tab is reactivated

**Status:** Completed.
**Source:** Bug report
`tasks/bug_reports/2026-07-27-journal-live-feed-misses-events-while-tab-inactive.md`
(full diagnosis and repro history there). Surfaced again and cleanly
demonstrated during the task-v1.7.0-3 live verification (2026-07-28/29): an
interrupted turn's assistant entry was on disk but absent from the already
-open live feed because the Journal tab was inactive when it was written; a
process restart (fresh page load) then showed it - the classic
"reappear-after-restart" signature confirming display-only staleness, never
data loss.

## Summary

The Journal panel's live feed can miss any turn's update - not just an
interrupted one - whenever the user is not looking at the Journal tab at the
moment the `journal_event` WebSocket delta arrives, and simply navigating
back to the tab does not recover it for an already-selected session. The
event is always correctly on disk; this is purely a browser-side live-view
freshness gap, a pre-existing debt from the v1.5.x journal UX work.

## Context (verified against current `src/jarvis/ui/status_console_ui/app.js`)

- `applyJournalEvent(payload)` (~line 1857) handles the live delta but
  returns immediately at `if (!_isJournalActive()) return;` (~line 1864).
  A user having a voice conversation is usually looking at Status, not
  Journal - so this drop is the common case, not an edge case.
- On reactivation, `setActiveView("journal")` (~line 824) and
  `_onJournalVisibilityChanged()` (~line 837) both call
  `refreshJournalSessions()` (~line 1427). That rebuilds the sidebar from a
  fresh `GET /api/journal/sessions`, but only re-fetches a session's *feed*
  (`selectJournalSession()`) when `_journalSelectedSessionId === null`
  (~lines 1448-1450). A session already selected before navigating away
  stays selected with no re-fetch, so its rendered feed keeps whatever it
  had the last time it was explicitly selected - missing every delta that
  arrived while away.
- **Trap for the fix - do not change `refreshJournalSessions()` to always
  re-fetch the selected feed.** `applyJournalEvent()`'s *tab-active* path
  (~line 1865) calls `refreshJournalSessions()` for the sidebar and then
  `_appendJournalTurn()` (~line 1899) to append just the one new turn -
  deliberately *not* a full `_renderJournalFeed()`/`replaceChildren()`,
  precisely so a currently-playing audio tile is not detached mid-playback.
  Making `refreshJournalSessions()` force a feed re-fetch would fire on every
  live event and re-introduce exactly that regression. The re-fetch must be
  scoped to the *activation* entry points, not the per-event path.
- The in-flight-fetch contributor the bug report listed as "unconfirmed"
  now appears wired: `selectJournalSession()` (~line 1615) defers via
  `_journalFeedRefetchSessionId` (~line 1876 in `applyJournalEvent`) and
  `_maybeRefetchJournalFeed()` (~line 1650) consumes it on every fetch
  completion. Whoever picks this up should confirm that path is sound and
  decide whether it needs any change, or only the tab-inactive case does.

## Current Boundary

- Standalone backlog fix. The Journal UX story that would naturally own this
  (`story-v1.5.2-journal-ux-pack`) is already closed, so this is not folded
  into any active story - the v1.7.0 barge-in story owns the interrupt
  cancellation core, not the Journal live-view surface.
- Scope is the client-side freshness gap only. The server side (write
  timing, `JournalEventAppended` publication before `finish_turn()` returns)
  is confirmed correct and out of scope - do not touch it.
- Recommended approach (option a from the bug report): on Journal
  (re)activation, after refreshing the sidebar, re-fetch the currently
  selected session's feed once - e.g. an explicit
  `selectJournalSession(_journalSelectedSessionId)` from the activation
  callers, or an activation-only flag threaded into
  `refreshJournalSessions()` - leaving the per-event append path untouched.
  Option b (track per-session "rendered feed is stale" client-side and
  reconcile on activation) is acceptable if it turns out cleaner; either way
  the trap above stands.

## Implementation note

- `refreshJournalSessions()` keeps the reactivation choice inline: the only
  pure predicate is whether an existing selection needs reconciliation, and
  extracting a one-use boolean helper would add indirection without making the
  DOM interaction more testable. The structural UI test instead pins both
  activation callers and the selected-session branch.
- Hidden deliberately clears `_journalSelectedSessionId`, so reopening it
  rebuilds around the newest session rather than claiming to restore a prior
  selection. A reactivated Journal with an active search reruns that search
  instead of clearing it through `selectJournalSession()`.

## Acceptance Criteria

- [ ] Reactivating the Journal tab (or bringing it back from Hidden) with a
      multi-turn session already selected shows every event that arrived
      while the tab was inactive, with no process restart.
- [ ] The tab-active live path is unchanged: a delta arriving while Journal
      is the active view still appends just its one turn, a currently
      -playing audio tile is not interrupted, and the feed is not fully
      re-rendered per event (no double-render).
- [ ] Switching away and back does not duplicate turns already rendered, and
      a session deleted/vanished while away is handled (no crash, sensible
      empty/selection state).
- [ ] A documented manual repro (per the project testing protocol this is a
      human-run WebView check that Python tests cannot exercise directly):
      Status tab focused -> run a turn (or interrupt one) -> switch to
      Journal -> the new entry is present in the open session's feed. Provide
      exact steps as a handoff. Factor out and unit-test any pure
      reactivation-refetch decision logic if it can be separated from the
      DOM.
- [ ] `python -m pytest` and Ruff stay green.

## Manual verification handoff

Run from the repository root:

```powershell
python -m jarvis --status-console
```

1. Open Journal and select a session that already has at least one turn.
2. Switch to Status, submit a text or voice turn, and wait until it is
   recorded. An interrupted turn is also a valid repro.
3. Return to Journal. Confirm the selected session immediately contains the
   new event without restarting Jarvis or selecting the session again.
4. With Journal active, play an existing audio tile. Submit another turn and
   confirm its event appends once, while the audio continues playing.
5. Switch away and back again. Confirm no event is duplicated. Delete or
   start a new session while away if practical; returning must not crash.
6. Enter a Journal search query, switch to Status, then return to Journal.
   Confirm the query and its filtered results remain active.

## Verification result

- Automated: `python -m ruff format --check .`, `python -m ruff check .`,
  and `python -m pytest` passed (1439 passed, 1 skipped).
- Manual: the reactivation, interrupted-turn, duplicate-prevention,
  active-audio, and search-preservation scenarios were verified by the human
  on 2026-07-29.
