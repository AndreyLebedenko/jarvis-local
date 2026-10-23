# Human-run handoff: personal proxy Journal and Status Console surfaces (task v2.1.0-10)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by
a human: it needs the microphone, the speakers, the GPU, the live local Ollama
endpoint and the Status Console window. The agent prepared it and ran none of it.

What it answers: after a real spoken and a real typed request in
`--personal-proxy`, does the Journal view show the proxy session with its
labels; does the dock accept typed requests once the session exists; does a dry
run leave the Journal empty; do the Status Console show the dry-run indicator
and the last block reason without any value; does `search_history` find the
proxy answer by its label and automatic retrieval never use it.

Documentation debt, stated on purpose: the user documentation of the whole
feature (README, config guide) is task v2.1.0-12 and does not exist yet. This
handoff does not rely on it; every key, command and default it needs is named
below with its source file. The preparation of the speech engine, Ollama and the
`[personal_proxy]` section is the one of `manual/personal-proxy-wiring-handoff.md`
(its part 1 and part 2); this file repeats the keys it depends on and does not
assume a starting state.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_journal_writer.py`,
`tests/test_personal_proxy_status_sink.py`,
`tests/test_personal_proxy_status_js_behavior.py`,
`tests/test_personal_proxy_ui.py`, `tests/test_ui_transport_personal_proxy.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. Jarvis reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`); a key that is
  absent means the code default.
- Start command (`parse_args` in `src/jarvis/app.py`):
  `python -m jarvis --status-console --personal-proxy`. The flag needs
  `--status-console` and excludes `--mcp-mode` and `--debug`.
- `[personal_proxy]` keys used (defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`; commented in `config.example.toml`):
  `endpoint`, `model`, `api_key_env` (default `"JARVIS_PERSONAL_PROXY_KEY"`, the
  NAME of the environment variable that holds the key), `dry_run` (default
  `true`), `topics_file` (default `"personal_proxy_topics.txt"`),
  `confirmation_timeout_seconds` (default `20`).
- `[journal]` keys used (`JournalSettings`, `src/jarvis/core/config.py`):
  `enabled` (default `true`) and `root` (default `"journal"`, relative to the
  working directory). One run writes one session directory
  `<root>/<session id>/` holding `events.jsonl` and the `.wav` files
  (`_EVENTS_FILE_NAME`, `src/jarvis/journal/store.py`).
- Hotkeys (`HotkeySettings`, `src/jarvis/core/config.py`; overridable in the
  `[hotkeys]` section of `config.toml`; check that section first): shutdown
  `Ctrl+Alt+Q` (`shutdown`), interrupt `Ctrl+Alt+I` (`interrupt`).
- Journal sources of the exchange (`src/jarvis/journal/proxy_exchange.py`):
  `proxy_heard` (your request, role user), `proxy_sent` (what went out, role
  system), `proxy_answer` (the restored answer, role assistant) and
  `proxy_notice` (content-free notices, role system).
- The window text is in the language of `[ui].language` (default `"en"`,
  `UiSettings`); this handoff names the English texts.

## 1. One-time preparation (state-independent)

1. Do part 1 (steps 1 to 4) of `manual/personal-proxy-wiring-handoff.md`, with
   `dry_run = false` in `[personal_proxy]` for parts 2 to 5 below. In
   `config.toml` make sure `[journal]` does not set `enabled = false` and either
   has no `root` key or has `root = "journal"`.
2. Delete the folder `journal` in the repository root (or move it away), so that
   the sessions you look at below are only the ones of this handoff. Do not do
   this if the folder holds history you want to keep: move it instead.
3. Close any running Jarvis (`Ctrl+Alt+Q`).

## 2. A spoken request and a typed request (Journal on, `dry_run = false`)

1. `python -m jarvis --status-console --personal-proxy`. Wait for the orb to read
   "Waiting for a request".
2. Open the Journal view (the "Journal" button in the top bar). Expected: the
   session list is empty; the input dock at the bottom shows the note beginning
   "Personal proxy: the Journal session starts with the first request" and no
   text box.
3. Say: "Расскажи коротко, что такое реле". Let the answer finish being spoken.
4. Expected in the Journal view without a restart: one new session titled
   "Personal proxy session" (not the text you said). Open it. Expected, in this
   order: an event labeled "Personal proxy - request" holding the whole heard
   text, with an audio tile and the note "Spoken request; the recording is
   stored with it."; an event labeled "Personal proxy - sent" holding the
   exact payload (the system prompt and your sanitized sentence); an event
   labeled "Personal proxy - external answer" holding the sentences you heard,
   joined. No event holds the placeholder mapping.
5. The dock now shows a text box and a Send button (the session is the active
   one and selected) but no Attach button. Type "Расскажи коротко, что такое
   диод" in the dock text box and press Send. Expected: the request runs through
   the proxy (blocks in the Status view's Personal proxy panel, the answer is
   spoken), NOT through the main model (the orb never reads "Thinking" for the
   main model, and `ollama ps` in another terminal never lists `[backend].model`),
   and the same session gains a second request/sent/answer triple.
6. In the Personal proxy panel (Status view) type "Привет" and press Send.
   Expected: a third triple in the same session (typed requests carry the note
   "Typed request." and have no audio tile).
7. Press `Ctrl+Alt+Q`.
8. In PowerShell, from the repository root:
   `Get-ChildItem journal` shows exactly one session folder;
   `Get-Content -Encoding UTF8 journal\<session id>\events.jsonl` shows, per
   request, lines whose `"source"` values are `proxy_heard`, `proxy_sent`,
   `proxy_answer` in that order. Expected: no line contains a `"mapping"` key,
   and no line contains a `<PERSON_` placeholder inside a `proxy_answer` text.
   Report any line that does.

## 3. Labels in search and in the model's tool

1. Start again (step 2.1). Open the Journal view, type "реле" into the search box
   ("Search exact words or prefixes"). Expected: hits from the proxy session
   labeled "Personal proxy - request" and "Personal proxy - external answer", not
   "Jarvis".
2. Say or type a request that makes the proxy session the only one that
   mentions a word, then close (`Ctrl+Alt+Q`) and start a NORMAL run:
   `python -m jarvis --status-console`. Ask by voice or in the dock:
   "Найди в истории разговор про реле". Expected: the model may use
   `search_history` and find the proxy items, which carry `source_kind`
   `proxy_request` / `proxy_answer` in the tool result (the result is visible in
   the debug transcript only with `--debug`; if you do not run `--debug`, judge
   from the model's reply that it names the item as coming from the personal
   proxy and not as its own earlier answer).
3. Ask the main model a question on the same topic WITHOUT mentioning history.
   Expected: the reply does not quote the proxy answer as if it were remembered
   (automatic retrieval never selects proxy records).
4. Still in the NORMAL run of step 3.2 (a fork is refused in the personal proxy
   run), open the Journal view, select the proxy session and press "Continue
   conversation" (`journal_session_continue`, `strings.js`). Expected:
   the new session starts without the proxy request and answer (the fork
   provenance note counts them as excluded).
5. Press `Ctrl+Alt+Q`.

## 4. The Status Console indicators

1. Set `dry_run = true` in `[personal_proxy]` and start the proxy run (step 2.1).
2. Expected, in the Personal proxy panel header: an amber label "DRY RUN -
   nothing is sent". It stays while the window is open and is back after you
   close and reopen the Status view (it is part of the state snapshot).
3. Say: "Позвони Марине Крыловой по номеру восемь девятьсот двенадцать триста
   сорок пять шестьдесят семь восемьдесят девять". Expected: the dry-run block as
   in the wiring handoff; if the gate found the phone number the line "Last stop:
   Blocked by the outbound check, nothing sent (phone number, message 1,
   characters N-M)" appears under the label. It names a category and positions
   and never the number. Report the exact line.
4. Say a request that is not blocked. Expected: the "Last stop" line disappears
   (a request that reaches the dry-run stop clears it).
5. Press `Ctrl+Alt+Q`. Expected: `Get-ChildItem journal` is unchanged since part 2
   (a dry run created no session and wrote no event). Report if a new folder
   appeared.
6. Set `dry_run = false`. Start the proxy run. Expected: no "DRY RUN" label.
   Make the gate refuse by saying a request that contains a spoken card number,
   for example "Оплати картой четыре два четыре два, четыре два четыре два,
   четыре два четыре два, четыре два четыре два" (if the sanitizer replaces it
   and nothing is blocked, the line stays absent; report which). When the line
   appears, close with `Ctrl+Alt+Q`, open the new session in the Journal view and
   find an event labeled "Personal proxy - notice" whose text reads like the
   Status line. Expected: the notice holds the kind and positions only, no number.

## 5. What to report

- Part 2: the titles and labels seen, whether the dock behaved as described, and
  whether any line in `events.jsonl` held a mapping or a placeholder answer.
- Part 3: the labels in search, and what the main model said about the proxy
  items and about the topic without history.
- Part 4: the exact "Last stop" line, and whether the dry run left `journal`
  untouched.
- Anything that differs from "Expected", with the text you saw.
