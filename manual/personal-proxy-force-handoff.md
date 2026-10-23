# Human-run handoff: the /force command (task v2.1.0-10d)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by
a human: it needs the Status Console window, the live local Ollama endpoint, and
(for part 2 only) an OpenAI-compatible chat endpoint of your choice. The agent
prepared it and ran none of it.

What it answers: does `/force` (and its short form `/f`) in the Journal dock send
one typed message without the local checks; does the outbound gate still block a
phone number in a forced message; does a forced message in dry run send nothing;
does an unknown command or a command without text send nothing and say so; is the
forced message marked in the Status panel and in the Journal feed; and does the
next message go the normal way.

Documentation debt, stated on purpose: the user documentation of the whole
feature (README, config guide) is task v2.1.0-12 and does not exist yet. This
handoff does not rely on it; every key, command, default and text it needs is
named below with its source file. The preparation of the speech engine, Ollama
and the `[personal_proxy]` section is the one of
`manual/personal-proxy-wiring-handoff.md` (its part 1 and part 2); this file
repeats the keys it depends on and does not assume a starting state.

Privacy, stated on purpose (the owner's decision of 2026-10-24, `PROJECT.md`
"Runtime locality contract"): a forced message skips the local model that finds
names and other personal text, so such text in it goes to the external endpoint.
The deterministic gate still runs, but it recognises only structured identifiers
in their usual written forms: names, addresses in free text, and spelled-out or
obfuscated numbers and e-mails are not recognised, and in a forced request nothing
else catches them. Restoration does nothing for a forced request (nothing was
replaced). Use only invented text in this handoff.

Known limitation, not fixed here: for an unknown command or a command without
text the dock still clears the text box and shows `Sent`, because it only knows
the message was accepted into the queue; the notice appears in the chat, and the
typed text is lost.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_request_commands.py`,
`tests/test_personal_proxy_force_pipeline.py`,
`tests/test_personal_proxy_force_blocks.py`,
`tests/test_personal_proxy_force_journal.py`,
`tests/test_personal_proxy_ui.py`,
`tests/test_personal_proxy_chat_js_behavior.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. Jarvis reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`); a key that is
  absent means the code default.
- Start command (`parse_args` in `src/jarvis/app.py`):
  `python -m jarvis --status-console --personal-proxy`.
- `[personal_proxy]` keys used (defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`): `endpoint` and `model` (default `""`, must be
  set), `api_key_env` (default `"JARVIS_PERSONAL_PROXY_KEY"`, the NAME of the
  environment variable that holds the key), `topics_file` (default
  `"personal_proxy_topics.txt"`, relative to the working directory) and `dry_run`
  (default `true`; part 1 and part 4 need `false`, part 3 needs `true`). After
  every change of `dry_run`, close and start the run again.
- `[journal]` keys (`JournalSettings`, `src/jarvis/core/config.py`): `enabled`
  (default `true`) and `root` (default `"journal"`). One session is one folder
  `<root>/<session id>/` holding `events.jsonl`.
- Hotkeys (`HotkeySettings`, `src/jarvis/core/config.py`; overridable in the
  `[hotkeys]` section of `config.toml`; check that section first): shutdown
  `Ctrl+Alt+Q`.
- The command syntax (`COMMAND_TABLE` and `parse_typed_request`,
  `src/jarvis/personal_proxy/request_commands.py`): a typed message whose first
  word is exactly `/force` or `/f` (lowercase) followed by the text. A first word
  that is a slash and letters only but is not one of those two (`/forse`,
  `/FORCE`, `/help`) is an unknown command. A first word with any other shape
  (for example `/etc/hosts`) is an ordinary message. Only the Journal dock text
  is parsed; a spoken request is never forced.
- The dock is the text box and "Send" button at the bottom of the Journal view
  (`journalInputDock` in `src/jarvis/ui/status_console_ui/index.html`). The views
  are the top bar buttons "Status" and "Journal" (`strings.js`).
- Texts below are English (`[ui].language` default `"en"`), keys in
  `src/jarvis/ui/status_console_ui/strings.js`:
  - Dock help line, shown under the text box in the proxy mode
    (`journal_input_force_help`):
    `/force text sends one message without the local checks (short form: /f)`.
  - Forced marker (`proxy_forced_marker`):
    `FORCED: sent without the local checks`.
  - Unknown command notice, chat text (`unknown_command`,
    `src/jarvis/personal_proxy/service_texts.py`):
    `Unknown command, nothing was sent. The known command is /force (or /f).`
  - Empty command notice, chat text (`empty_command`):
    `There is no text after the command, nothing was sent.`
  - Gate block notice, chat text (`gate_blocked`): starts with
    `Blocked by the check, nothing was sent:` and names the category, here
    `a phone number`, with a message number and character positions, never the
    number itself.
  - Dry run block title (`proxy_block_dry_run`): `Dry run - nothing was sent`.
  - Block titles (`strings.js`): `Heard` (`proxy_block_heard`),
    `Sent to the external model` (`proxy_block_sent`), `Notice`
    (`proxy_block_notice`).
  - Journal event label (`journal_source_proxy_sent`):
    `Personal proxy - sent`.
- The standard system prompt is `DEFAULT_SYSTEM_PROMPT` in
  `src/jarvis/personal_proxy/payload.py`; it is folded behind the label
  `Standard system prompt (click to show)` (`proxy_sent_default_system`).

## 1. A forced message goes out, marked (`dry_run = false`)

1. Set `dry_run = false` in `[personal_proxy]`. Run
   `python -m jarvis --status-console --personal-proxy`. Wait for the orb to read
   "Waiting for a request". Open the Journal view.
2. Expected: under the text box the dock shows the help line from the references
   (`/force text sends one message ...`). Click an older session row if one
   exists: the text box is hidden and so is the help line.
3. Without the command, type "What is a relay?" and press Send (or Enter). Note
   what happens: the local model may accept it (the answer is shown) or refuse it
   falsely (a notice such as "The request was refused" or "The request could not
   be prepared"). This is the baseline; either outcome is fine for the next steps.
   If the local model refused it, the Status panel shows the "Last stop:" line.
4. Type `/force What is a relay?` and press Send. Expected: the dock status line
   reads `Sent`; the Status panel shows, in this order, a "Heard" block holding
   `What is a relay?` (without the word `/force`) and the line
   `Sending without a question`, then a "Sent to the external model" block whose
   first line is the forced marker from the references, then the answer, which is
   spoken. No question was asked and no refusal appeared even if step 3 was
   refused.
5. In the Journal view, in the selected session, find the event labeled
   "Personal proxy - sent". Expected: the same forced marker is shown on it, the
   fold label above the text, and the line `user: What is a relay?` (no `/force`).
6. Type `/f What is a diode?` and press Send. Expected: the same as step 4 (the
   short form works), with the text `What is a diode?`.
7. Press `Ctrl+Alt+Q`. In PowerShell from the repository root:
   `Get-Content -Encoding UTF8 journal\<session id>\events.jsonl` (the newest
   folder of `Get-ChildItem journal`). Expected: each forced request left a
   `proxy_heard` line (`"origin": "typed"`, `"decision": "send_without_question"`),
   a `proxy_sent` line whose `metadata` holds `"forced": true`, and a
   `proxy_answer` line. The step 3 request, if it was sent, has a `proxy_sent`
   line WITHOUT the `forced` key.

## 2. The gate still applies (`dry_run = false`)

1. Run `python -m jarvis --status-console --personal-proxy` again. In the Journal
   dock type `/force Call me on +7 912 345-67-89 tomorrow` and press Send.
2. Expected: a "Heard" block shows your text, and then a "Notice" block starts with
   `Blocked by the check, nothing was sent:` and names `a phone number`; no
   "Sent to the external model" block appears, no answer, and the notice does not
   print the number. The Status panel shows the "Last stop:" line with the gate
   block. Nothing reached the external endpoint (check the provider's request
   log, if it has one).
3. Type `/force The topic is `, followed by one line copied from your topics file
   (`topics_file`; skip this step if the file is absent or empty), and press Send.
   Expected: blocked the same way, naming `text from the topics file`.
4. Press `Ctrl+Alt+Q`.

## 3. Dry run with force (`dry_run = true`)

1. Set `dry_run = true`. Run `python -m jarvis --status-console --personal-proxy`.
   In the Journal dock type `/force What is a relay?` and press Send.
2. Expected: the dock status line reads `Sent. In dry run the result is in the
   Status view, and nothing is written to the Journal.` The Status view shows one
   block "Dry run - nothing was sent" whose first line is the forced marker; it
   shows `What is a relay?` as both the checked text and the sanitized text, an
   empty mapping, and the outbound gate as `passed`.
   No "Sent" block, no answer, nothing spoken, and the Journal folder gained no
   session (`Get-ChildItem journal` before and after has the same entries).
3. Press `Ctrl+Alt+Q`.

## 4. Commands that send nothing, and the next message (`dry_run = false`)

1. Set `dry_run = false`. Run `python -m jarvis --status-console --personal-proxy`.
2. Type `/forse What is a relay?` and press Send. Expected: a "Notice" block with
   the unknown command text from the references; nothing is sent, no "Heard"
   block, nothing spoken.
3. Type `/force` alone and press Send. Expected: a "Notice" block with the empty
   command text from the references; nothing is sent.
4. Type `/FORCE What is a relay?` and press Send. Expected: the unknown command
   notice (the command is lowercase only).
5. Type `/etc/hosts is a file on a computer, what is it for?` and press Send.
   Expected: an ordinary message: it goes the normal way (the local check and
   sanitize run, as in part 1 step 3), with NO forced marker.
6. Type `/force What is a relay?` and press Send, then type `What is a resistor?`
   and press Send. Expected: the first is marked forced; the second is a normal
   request with NO forced marker (one message, once).
7. Press `Ctrl+Alt+Q`.

## 5. Optional: a spoken request is never forced (`dry_run = false`)

Prepare the microphone and speech engine as in part 1 and part 2 of
`manual/personal-proxy-wiring-handoff.md`, then run
`python -m jarvis --status-console --personal-proxy`.

1. Say aloud "Force. What is a relay?". Expected: the request goes the normal path
   (heard, the local check and sanitize, possibly a question), and its "Sent to the
   external model" block has NO forced marker. A spoken command word is only words.
2. Press `Ctrl+Alt+Q`.

Honest limit: the guarantee is structural (only typed dock text is parsed for a
command, `RequestIntake` in `src/jarvis/personal_proxy/request_intake.py`) and is
covered by the automated tests in `tests/test_personal_proxy_force_pipeline.py`;
speech recognition would not write a literal slash anyway, so this part is a
sanity check, not the proof.

## What to report

- Part 1: whether the help line showed (and hid on an older session); what the
  step 3 baseline did; for steps 4 and 6 whether the Heard text had no `/force`,
  whether the forced marker showed in the Status panel and in the Journal feed,
  whether any question was asked; the `events.jsonl` lines (kinds, `forced` key,
  `origin`).
- Part 2: whether the phone number and the topic line were blocked, the notice
  text, and whether anything reached the endpoint.
- Part 3: the Dry run block (marker, text, gate) and whether the Journal changed.
- Part 4: for each step, whether the notice or the marker was as written; for any
  difference, the text you saw instead.
