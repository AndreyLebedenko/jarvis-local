# Journal search labels every hit "Jarvis", including the user's own turns

**Commit:** `fe9ba16` (branch `feat/v2.0-6-journal-and-console-surfaces`,
detected during task v2.0-6 slice S1).

## Symptoms

A Journal search for a phrase the user typed shows every result row with the
source label "Jarvis", including hits on their own turns: a voice turn and a
typed turn both read plain "Jarvis". The label is the assistant label for all
hits regardless of role or source.

## Current cause

`app.js` `_journalSearchHitElement()` hardcoded
`source.textContent = uiString("journal_source_assistant")`. The search hit
payload carried no source at all, so the client had nothing truthful to
render.

## Temporary decision

Slice S1 only branches on `hit.source === "mcp_canvas"` and labels an
external answer with its caller; every other hit keeps the existing
constant. The real fix - render `_journalSourceLabel(hit.source)` for all
hits, so a user turn reads "Voice"/"Clipboard"/"Typed" - is out of the card's
boundary ("normal rows: only a branch on the event's source, nothing else",
and the card asks only for the external-answer label).

The payload already carries `source` for every hit as of S1, so the follow-up
is a one-line client change plus its test.

## Future considerations

- Fix it in the same surface that owns search rendering, with a test that a
  user-role hit is not labeled "Jarvis".
- Do not bundle it into a slice that has a narrower boundary; it is a
  pre-existing mislabel, not a regression from v2.0.