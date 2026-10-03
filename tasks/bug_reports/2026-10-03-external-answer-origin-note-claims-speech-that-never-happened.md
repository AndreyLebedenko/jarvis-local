# External answer row says "Spoken as..." for an item that was never spoken

**Commit:** `8c903d7` (`main`; found while staging the v2.0.0 screenshots on
branch `release/v2.0.0-prep`).

## Symptoms

A Journal row for an `mcp_canvas` event whose speech status is `skipped`
(dropped from the queue by an interrupt) shows two contradicting notes:

- "Spoken as a short guide." / "Озвучен краткий пересказ."
- "Dropped before it was spoken." / "Выброшено из очереди до озвучивания."

The same happens for `muted` and `failed`, where nothing was heard either.

## Suspected cause

`_journalExternalAnswerDetail()` (`src/jarvis/ui/status_console_ui/app.js`)
renders the origin note whenever `metadata.speech_origin` is present, and the
recorder stores the origin the item was planned with, not whether speech
happened. The origin strings (`journal_external_answer_origin_*` in
`strings.js`) are worded as past facts ("Spoken ...").

## Temporary decision

Left as is for v2.0.0: the status note is correct and shown right below, so
the row is not misleading about the outcome, only redundant and
self-contradicting. The v2.0.0 screenshots avoid a `skipped` row. Changing it
now would be a UI behavior change after the owner's release run.

## Future considerations

- Either hide the origin note when the status is not `spoken` (and not
  `interrupted`, where part of it was heard), or reword the origin strings
  as the plan ("Planned as a short guide").
- One test per status in `tests/test_journal_view_ui.py`.
