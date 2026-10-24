# Human-run handoff: rename a session (task v2.1.0-10f)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by a
human in the Status Console window (a visual and keyboard check). The agent prepared it
and ran none of it. It needs no model request: renaming only writes a small file.

What it answers: can any session, including the live one and a proxy session, be renamed
from its "..." menu; does the new name show in the session list, in the search results
header and in "Copy title" and "Show info"; does an emptied name restore the automatic
one; do the limits hold; does a name survive a restart; is the name kept in its own file
and out of the event records.

Documentation debt, stated on purpose: the user documentation of the whole feature
(README, config guide) is task v2.1.0-12 and does not exist yet. This handoff does not
rely on it; every command, key and default it needs is named below with its source.

Privacy: the name is text you type; it stays on this machine, in the session folder. It
is not sent to any model or endpoint.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_journal_session_metadata.py`,
`tests/test_ui_transport_session_rename.py`,
`tests/test_journal_session_rename_js_behavior.py`, and the title cases in
`tests/test_status_console.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. Jarvis reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`); a key that is absent
  means the code default.
- Start command (`parse_args` in `src/jarvis/app.py`):
  `python -m jarvis --status-console`. For the proxy session part, start instead with
  `python -m jarvis --status-console --personal-proxy` and use a session that already
  exists, or create one as in `manual/personal-proxy-session-ux-handoff.md`; no request
  has to be sent to the external endpoint for this check.
- `[journal]` keys (`JournalSettings`, `src/jarvis/core/config.py`): `enabled` (default
  `true`) and `root` (default `"journal"`, relative to the repository root when started
  there). One session is one folder `<root>/<session id>/` holding `events.jsonl`; a
  renamed session also holds `session.json` (`SESSION_METADATA_FILE_NAME`,
  `src/jarvis/journal/session_metadata.py`).
- Shutdown hotkey (`HotkeySettings.shutdown`, `src/jarvis/core/config.py`; overridable in
  the `[hotkeys]` section of `config.toml`, check it first): `Ctrl+Alt+Q`. Without a
  working hotkey, close the console window and stop the `python -m jarvis` process in
  the terminal.
- The limit (`MAX_SESSION_TITLE_CHARS`, `src/jarvis/journal/session_metadata.py`): 80
  characters. Texts below are English (`[ui].language` default `"en"`); the Russian
  strings are in `src/jarvis/ui/status_console_ui/strings.js`.
- Opening the session menu (`initContextMenuTrigger` in `app.js`): the "..." button at the
  right of a session row in the Journal view, or right-click on the row, or Shift+F10 with
  the row focused. The entry is "Rename". The dialog is "Rename session": a text field,
  a counter `N / 80`, the hint "Leave empty to restore the automatic name.", and the
  buttons Cancel and Save. Enter in the field saves, Escape cancels.

## Steps

State-independent start: any journal with at least two sessions will do. If `<root>` is
empty or has one session, use the app for a short while (speak or type a request in the
Journal dock) and end it with the "New context" button, so that a second session exists.
Every step below says what you should see; write down the first step that differs.

1. Start `python -m jarvis --status-console`, open the Journal view (the "Journal" button
   in the top bar). Pick an older session (not the live one). Open its "..." menu: the
   entry "Rename" is there.
2. Choose "Rename". The dialog opens with an empty field (the session has no name of
   its own yet), the automatic name is shown only as grey placeholder text (one line, cut
   with `...` if long), the counter reads `0 / 80`. Press Enter with the field empty: the
   dialog closes, nothing changes and no `session.json` appears in the session folder.
   Open "Rename" again.
3. Type `Pump notes` and press Enter. The dialog closes and the
   session row now reads `Pump notes`.
4. Open the same "..." menu: "Copy title", then paste somewhere (for example the search
   box): `Pump notes`. "Show info": the line "Name" reads `Pump notes`.
5. Search: type a word that occurs in that session's messages into the search box. The
   result group of that session has the header `Pump notes`. (The search matches message
   text only, not titles; that is expected.)
6. Reset: "Rename" again (the field now holds `Pump notes`, selected; saving it unchanged
   changes nothing), clear the field (Ctrl+A, Delete) and press Save. The row shows
   the automatic title again: the first request text, or for a proxy session
   `Personal proxy session YYYY-MM-DD HH:MM` with the start date and time of that session.
7. Limits: "Rename", paste 100 characters of text. The field stops at 80 characters and the
   counter reads `80 / 80`. Press Escape: the dialog closes and the title is unchanged.
8. The live session: select the session marked as the current one (the one without the
   delete and continue buttons) and rename it to `Live now`. It is accepted and shown.
9. A proxy session (only in the `--personal-proxy` start): rename it to `Trip plan`. The
   row shows `Trip plan` and still carries the proxy marker icon and the amber edge.
10. Restart: press `Ctrl+Alt+Q`, start the same command again, open the Journal view. The
    names from steps 8 and 9 (and 3 if you did not reset it) are still shown.
11. The file: in the terminal, from the repository root, run
    `Get-Content -Raw -Encoding UTF8 journal/<session id>/session.json` for a renamed
    session (use your `[journal].root` if you changed it). Expect a JSON object with
    `"version": 1` and `"title"`. Its `events.jsonl` is unchanged in size by renaming
    (compare `(Get-Item journal/<session id>/events.jsonl).Length` before and after one
    more rename).
12. Delete: delete one renamed, non-live session with its delete button and confirm. Its
    whole folder, including `session.json`, is gone from `<root>`.

## What to report

For each step number: the same as expected, or what you saw instead (the exact title
text, the message in the dialog). A refusal message in the dialog (red text under the
field) that you did not expect is a finding; write its text.
