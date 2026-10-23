# Human-run handoff: request input in the Journal dock (task v2.1.0-10c)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by
a human: it needs the microphone, the speakers, the GPU, the live local Ollama
endpoint and the Status Console window. The agent prepared it and ran none of it.

What it answers: in the real window, does the Status "Personal proxy" panel have
no input and still show the live blocks; does the Journal dock take a typed
request at start, in dry run, and after "New context"; is the dock inactive, with
a note, when an older session is selected; does the feed show the empty
"new session" state after "New context"; and is the standard system prompt
folded in the "sent" block, in both the Status panel and the Journal feed.

Documentation debt, stated on purpose: the user documentation of the whole
feature (README, config guide) is task v2.1.0-12 and does not exist yet. This
handoff does not rely on it; every key, command, default and text it needs is
named below with its source file. The preparation of the speech engine, Ollama and
the `[personal_proxy]` section is the one of `manual/personal-proxy-wiring-handoff.md`
(its part 1 and part 2); this file repeats the keys it depends on and does not
assume a starting state.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_input_dock_js_behavior.py`,
`tests/test_personal_proxy_ui.py`, `tests/test_personal_proxy_chat_js_behavior.py`,
`tests/test_personal_proxy_chat_sink.py`, `tests/test_status_console.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. Jarvis reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`); a key that is
  absent means the code default.
- Start command (`parse_args` in `src/jarvis/app.py`):
  `python -m jarvis --status-console --personal-proxy`.
- `[personal_proxy]` keys used (defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`): `dry_run` (default `true`; part 2 needs `false`,
  part 1 needs `true`), plus the keys of the wiring handoff (`endpoint`, `model`,
  `api_key_env`, `topics_file`). After every change of `dry_run`, close and start
  the run again.
- `[journal]` keys (`JournalSettings`, `src/jarvis/core/config.py`): `enabled`
  (default `true`) and `root` (default `"journal"`). One session is one folder
  `<root>/<session id>/` holding `events.jsonl`.
- Hotkeys (`HotkeySettings`, `src/jarvis/core/config.py`; overridable in the
  `[hotkeys]` section of `config.toml`; check that section first): shutdown
  `Ctrl+Alt+Q`.
- The views: the top bar buttons "Status" and "Journal" (`view_status`,
  `view_journal`, `strings.js`). The "New context" button is in the Journal view
  (`journalNewContextButton`, `strings.js` key `journal_new_context`). The dock is
  the text box and "Send" button at the bottom of the Journal view
  (`journalInputDock` in `src/jarvis/ui/status_console_ui/index.html`).
- Texts below are English (`[ui].language` default `"en"`), keys in `strings.js`:
  - Status panel hint, shown while the panel has no block (`proxy_chat_empty`):
    `Speak a request, or type it in the Journal dock.`
  - Dock note for an older session (`journal_input_proxy_note`):
    `Personal proxy: this is an older session and does not take requests. Select the live session, or start a new context, to type here.`
  - Empty feed after "New context" (`journal_proxy_new_session_empty`):
    `New session. It starts with your first request.`
  - Dock status line after a send in dry run (`journal_input_sent_dry_run`):
    `Sent. In dry run the result is in the Status view, and nothing is written to the Journal.`
  - Dock status line after a send otherwise (`journal_input_sent`): `Sent`.
  - Dock status line after "New context" (`journal_new_context_ready_proxy`):
    `New session ready. Speak a request, or type it here.`
  - Status panel block title (`proxy_block_sent`): `Sent to the external model`.
  - Fold label of the standard system prompt (`proxy_sent_default_system`):
    `Standard system prompt (click to show)`.
  - Journal event label (`journal_source_proxy_sent`): `Personal proxy - sent`.
- The standard system prompt is `DEFAULT_SYSTEM_PROMPT` in
  `src/jarvis/personal_proxy/payload.py`: `Answer in the language of the request. Keep placeholders such as <PERSON_1> exactly as written.`
  It cannot be changed from `config.toml`, so the "a changed prompt is shown in
  full" half of the rule is covered only by automated tests
  (`tests/test_personal_proxy_chat_js_behavior.py`,
  `tests/test_status_console.py`) and not by this handoff.

## 1. Dry run (`dry_run = true`)

1. Set `dry_run = true` in `[personal_proxy]`. Run
   `python -m jarvis --status-console --personal-proxy`. Wait for the orb to read
   "Waiting for a request".
2. Open the Status view. Expected: the "Personal proxy" panel shows the amber
   label "DRY RUN - nothing is sent", the hint from the references, the module
   chips above it, and NO text box and NO Send button anywhere in the panel.
3. Open the Journal view. Expected: the dock shows a text box and a Send button
   (enabled) and no Attach button, and no inactive-session note, whether the
   session list is empty or holds sessions from earlier runs. The feed shows
   `New session. It starts with your first request.` (no older session is opened
   on its own), and under the text box the note `No live session: a request
   typed here starts a new session.` (`journal_input_proxy_new_session_note`).
   Click an older row: its events show and the dock stays enabled.
4. Type "Расскажи коротко, что такое реле" in the dock text box and press Send
   (or Enter). Expected: the text box empties, the dock status line reads the
   dry-run line from the references. The Journal gains no new session folder
   (`Get-ChildItem journal` before and after has the same entries).
5. Open the Status view. Expected: one block "Dry run - nothing was sent" holding
   your sentence; nothing is spoken.
6. Press `Ctrl+Alt+Q`.

## 2. Sending (`dry_run = false`)

1. Set `dry_run = false`. Run
   `python -m jarvis --status-console --personal-proxy`. Wait for the orb to read
   "Waiting for a request". Open the Journal view. Expected: the dock is enabled
   (text box and Send, no Attach).
2. If the session list is empty, the feed shows the "New session" text from the
   references. Type "Расскажи коротко, что такое диод" in the dock and press
   Send. Expected: the dock status line reads `Sent`; a session row appears and
   becomes selected on its own; the feed gains the request, the sent payload and
   the answer; the answer is spoken; `ollama ps` never lists `[backend].model`
   (the typed request goes to the proxy, not the main model).
3. In the Status view the blocks "Heard", "Sent to the external model" and the
   answer appear. In the "Sent" block the system prompt is NOT printed: instead a
   line with the fold label from the references, and your sentence below it
   (with placeholders such as `<PERSON_1>` if the sanitizer replaced something).
   Click the fold label. Expected: it opens and shows the standard system prompt
   text from the references; click again, it closes.
4. In the Journal view, in the selected session, find the event labeled
   "Personal proxy - sent". Expected: the same fold label above, and under it the
   line `user: ...` with your sanitized sentence; no `system: ...` line is
   printed until you click the fold label.
5. Press `Ctrl+Alt+Q`. In PowerShell from the repository root:
   `Get-Content -Encoding UTF8 journal\<session id>\events.jsonl` (the newest
   folder of `Get-ChildItem journal`). Expected: the `proxy_sent` line still holds
   the whole text `system: Answer in the language of the request. ...` followed by
   `user: ...` (the record is not changed; only the display folds it).

## 3. New context and an older session

1. Start the run again (the start command from the references, `dry_run = false`).
   Say: "Объясни, что такое трансформатор". Let
   the answer finish. Open the Journal view. Expected: the session row of this
   run is selected and the dock is enabled.
2. Press "New context". Expected: no confirmation dialog; the dock status line
   reads the "New session ready" line from the references; the feed shows
   `New session. It starts with your first request.`; NO session row is
   highlighted; the Status panel shows its hint again (the blocks are gone); the
   dock text box and Send stay enabled.
3. Click the older session row. Expected: its events show; the dock is still
   enabled (no live session exists yet).
4. Type "Привет" in the dock and press Send. Expected: a NEW session row appears
   and becomes selected (not the older one); the feed shows only this request's
   events; the old session did not gain an event.
5. Click the older session row again. Expected: its events show, the text box and
   Send button are gone, and the dock shows the older-session note from the
   references (no Attach button either).
6. Click the new (live) session row. Expected: the text box and Send button are
   back.
7. Press "New context" and then say: "Расскажи про реле". Expected: the session
   appears and is selected on its own, like in step 4, without typing.
8. Press `Ctrl+Alt+Q`.

## 4. Attachments stay refused

1. Run `python -m jarvis --status-console --personal-proxy` again. In the Journal
   view, drag any small file onto the dock. Expected: the dock shows no Attach button
   and no drop area, and the file is not queued or sent (the proxy mode takes no
   attachments).
2. Press `Ctrl+Alt+Q`.

## What to report

- Part 1: whether the Status panel had any input; whether the dock was enabled in
  dry run; the dock status line; whether the Journal folder gained a session.
- Part 2: whether the typed request went through the proxy (and not the main
  model); the Status "Sent" block and the Journal "sent" event: the fold label,
  the click behaviour, and whether `events.jsonl` still holds the system line.
- Part 3: for each step, whether the dock and the feed did what is written; for
  any difference, the text you saw instead.
- Part 4: whether any file was accepted.
