# Live-appended Journal message: "More actions" button is enabled but does nothing

**Detected:** 2026-09-26, owner playtest during the generation-profiles
handoff (`tasks/done/task-config-generation-profiles-handoff.md`).
**Commit:** `f9c2d2f` (branch `feat/config-generation-profiles`, uncommitted
work unrelated to the Journal UI).

## Symptoms

In the Journal tab's feed, the most recent user voice message shown (the one
that arrived live while the tab was open) has an enabled "More actions" /
"Ещё действия" (`...`) button. Clicking it opens nothing and shows no feedback.
Switching to another tab and back fixes it: the button then opens the menu
normally.

## Suspected cause

A message that arrives live is rendered without its event position, and the
position is exactly what that message's menu entries need.

- `src/jarvis/ui/transport.py` `_on_journal_event_appended` pushes the
  `journal_event` delta with `journal_event_payload(event.event, ...)` only.
  The bus event `JournalEventAppended` (`src/jarvis/journal/events.py`)
  carries `reference` (session id + event position), but the push drops it.
- `status_console_ui/app.js` therefore renders live appends with
  `position === null`, by design ("never a live append whose position is not
  yet known"). Replay, the transcript panel, and the `data-event-position`
  attribute are all omitted.
- `_journalMessageMenuEntries` builds its entries from exactly those parts:
  copy (answers only), replay, pause, transcribe, annotate-this-message. For
  a live user voice message every entry is falsy.
- `openContextMenu` (`status_console_ui/interaction.js`) returns silently
  when no entries are visible, so the button stays enabled and does nothing.
- A tab switch re-renders the feed in full from the HTTP endpoint, which
  knows positions, and the menu works.

User text messages are probably affected the same way. They have no copy
entry either, since copy is for answers, so they are likely to show the same
dead button. This has not been checked live.

## Temporary decision

Left as is. It is outside the generation-profiles change, and a tab switch
works around it.

Nearby alternatives considered for the fix:

- **Chosen for the fix: send the position with the live push.** Include
  `reference` in the `journal_event` delta and render a live append as a
  full-render message. This removes the root cause: the live message then
  also gets replay and the transcript panel, which it currently lacks for the
  same reason.
- **Not chosen: disable or hide the button when the menu would be empty.**
  This hides the symptom, but the message still lacks the actions a full
  render would give it. It is worth keeping as a defensive rule in
  `openItemContextMenu` anyway: an enabled control that does nothing is the
  actual UX defect.

## Future considerations

- Live-append handling was written when positions were unknown client-side.
  Check that the order of live appends and full renders cannot give a
  position to the wrong row, for example when a live append races a full
  feed refresh.
- The hidden-mode suppression in `_on_journal_event_appended` must stay in
  front of any new payload field.
