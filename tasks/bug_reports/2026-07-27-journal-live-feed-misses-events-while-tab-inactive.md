# Journal live feed misses events added while the Journal tab is inactive

**Commit where detected:** `24615bf` (task-v1.7.0-2, interrupt hotkey and
cancellation core).
**Backlog task:** `tasks/backlog/journal-live-feed-stale-on-tab-reactivation.md`
(filed 2026-07-29 after the bug was cleanly re-demonstrated during the
task-v1.7.0-3 live verification). This report stays the full diagnosis; the
backlog card carries the fix boundary and acceptance criteria.

## Symptoms

Owner report, reproduced twice on real hardware: interrupted Jarvis
mid-response via the hotkey during the "thinking" phase. The
just-spoken voice request did not appear in the Journal panel's already
-open session feed. After fully closing and restarting Jarvis (a fresh
page load), the entry was there, in the same session, correctly. This
is not data loss - `JournalStore` had the event and its WAV on disk the
whole time - it is a live-view staleness bug.

The owner confirmed they had scrolled the open session's feed all the
way to the bottom before concluding the entry was missing, and that the
session in question was the same multi-turn session that already
contained the two prior (uninterrupted) turns - so this is specifically
about a *live update to an already-open session*, not a missing session
in the sidebar list.

## Suspected cause

`src/jarvis/ui/status_console_ui/app.js`:

- `applyJournalEvent()` (~line 1857), the handler for the `journal_event`
  WebSocket delta (published by `JournalRecorder._append_event()` via
  `JournalEventAppended`), returns immediately if
  `_isJournalActive()` is false (~line 1864) - i.e. the Journal tab was
  not the active view at the moment the event arrived. A user having a
  voice conversation is not necessarily looking at the Journal tab, so
  this is the common case, not an edge case.
- `refreshJournalSessions()` (~line 1427), called when switching back to
  the Journal tab (`setActiveView()`, ~line 823-824), refreshes the
  sidebar's session list from a fresh `GET /api/journal/sessions` (so
  sizes/summaries look current) but only calls `selectJournalSession()`
  - the function that actually fetches and renders a session's event
    feed - when `_journalSelectedSessionId` is `null`. If a session was
    already selected before navigating away, it stays selected without
    a re-fetch, so its rendered feed keeps whatever content was fetched
    the last time it was explicitly selected.

Net effect: an event delta that arrives while the Journal tab is
inactive is dropped by the first guard, and simply navigating back to
the tab does not recover it, because the second function does not treat
"tab reactivated" as a reason to re-fetch an already-selected session's
feed.

**Confirmed, not just suspected (2026-07-28):** the owner re-ran the same
interrupted-during-thinking scenario with the Journal tab kept active
throughout, on a fresh "New context" session. The voice bubble (0:01,
matching a turn cancelled almost immediately) rendered live, in place,
with no restart needed. This isolates the cause to the `_isJournalActive()`
guard specifically - the server side (write timing, `JournalEventAppended`
publication) is confirmed not at fault under either condition, since the
only variable between the failing and passing runs was which tab had
focus when the event arrived.

A second, unconfirmed contributor in the same function: `_appendJournalTurn()`
is also skipped (and the event queued via `_journalFeedRefetchSessionId`
instead) if `_journalFeedFetchesInFlight > 0` when the delta arrives.
Whether `_journalFeedRefetchSessionId` is ever actually consumed to
trigger the deferred re-fetch was not traced - worth checking if the
primary fix does not fully explain reproductions where the tab *was*
active throughout.

Not caused by and not related to task-v1.7.0-2's own work: the
server-side race that motivated `Orchestrator.finish_turn()` to await
`journal_recorder.wait_for_pending()` was confirmed fixed by direct
reproduction (real `JournalRecorder`/`JournalStore`, no fakes) - the
event and its WAV are written to disk, and `JournalEventAppended` is
published, before `finish_turn()` returns in every case tested. This
report is about what the browser does with that event after it arrives,
which is a pre-existing gap from the journal UX work (v1.5.x), newly
noticed because an interrupted turn's very short duration makes it more
likely a user glances at another tab and back within the same session.

## Temporary decision

Left unfixed for now and filed as its own report rather than folded into
task-v1.7.0-2: this is a general Journal live-view freshness bug that
would affect *any* turn's live update (not just an interrupted one) if
the user is not looking at the Journal tab when the event fires - fixing
it belongs to whichever story owns the Journal UX surface, not the
interrupt hotkey's cancellation core. Task-v1.7.0-2's own acceptance
criteria (hotkey stops playback/backend, returns to listening, a
following turn works, idle press is a no-op, journal data is not lost)
are unaffected and remain verified.

## Future considerations

- Likely fix shape: either (a) have `setActiveView("journal")` and/or
  `_onJournalVisibilityChanged()` re-fetch the currently selected
  session's feed unconditionally on activation (not just the sidebar
  list), or (b) track "is this session's rendered feed stale" client-side
  and reconcile on activation instead of relying solely on live deltas.
- Trace whether `_journalFeedRefetchSessionId` is ever consumed - if not,
  the in-flight-fetch race is a second, independent instance of the same
  class of bug and should be fixed alongside the tab-inactive case, not
  separately.
- Worth a small manual check script or Playwright-style scenario once
  someone picks this up, given it is a browser-state bug that automated
  Python tests cannot exercise directly.
