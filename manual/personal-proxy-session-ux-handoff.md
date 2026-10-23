# Human-run handoff: personal proxy session marker and "New context" (task v2.1.0-10b)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by
a human: it needs the microphone, the speakers, the GPU, the live local Ollama
endpoint and the Status Console window. The agent prepared it and ran none of it.

What it answers: do proxy sessions and proxy messages carry the icon and the
amber edge and look right (the Status Console has one dark theme only, there is no
light theme to check); does the "New context" button start a new proxy session
lazily while idle; is it refused with a visible reason during a request and
during a pending question; does the next request after it land in a new session
and nothing of the old request or answer in it.

Documentation debt, stated on purpose: the user documentation of the whole
feature (README, config guide) is task v2.1.0-12 and does not exist yet. This
handoff does not rely on it; every key, command and default it needs is named
below with its source file. The preparation of the speech engine, Ollama and the
`[personal_proxy]` section is the one of `manual/personal-proxy-wiring-handoff.md`
(its part 1 and part 2); this file repeats the keys it depends on and does not
assume a starting state.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_personal_proxy_session_ux_ui.py`,
`tests/test_personal_proxy_journal_writer.py`,
`tests/test_personal_proxy_runtime.py`,
`tests/main_split/test_main_personal_proxy.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs. Jarvis reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`); a key that is
  absent means the code default.
- Start command (`parse_args` in `src/jarvis/app.py`):
  `python -m jarvis --status-console --personal-proxy`.
- `[personal_proxy]` keys used (defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`): `dry_run` (default `true`; this handoff needs
  `false`), `confirmation_timeout_seconds` (default `20`; this handoff needs
  `120` so a pending question stays up while you look at the button), plus the
  keys of the wiring handoff (`endpoint`, `model`, `api_key_env`, `topics_file`).
- `[journal]` keys (`JournalSettings`, `src/jarvis/core/config.py`): `enabled`
  (default `true`) and `root` (default `"journal"`). One session is one folder
  `<root>/<session id>/` holding `events.jsonl`.
- Hotkeys (`HotkeySettings`, `src/jarvis/core/config.py`; overridable in the
  `[hotkeys]` section of `config.toml`; check that section first): shutdown
  `Ctrl+Alt+Q`.
- The button: "New context" in the Journal view (`journalNewContextButton`,
  `strings.js` key `journal_new_context`). Texts below are English (`[ui].language`
  default `"en"`):
  ready `New session ready. Speak a request, or type it here.`
  (`journal_new_context_ready_proxy`), proxy not running `The personal proxy is not
  running.` (`journal_new_context_unavailable`),
  refused `A request is in progress or a question is waiting. Try again when it ends.`
  (`journal_new_context_busy_proxy`), marker tooltip
  `Personal proxy: this goes to the external service` (`journal_proxy_marker`),
  the normal-mode leave confirmation `Start a blank context and leave the
  current one?` (`journal_new_context_confirm`), which the proxy mode must NOT show.
- The live chat of the Personal proxy panel (Status view, `proxyChat`): the
  read-only blocks list (it has no text box since task v2.1.0-10c).
- The marker: an arrow-out-of-a-box icon in the title of a proxy session row and
  in the header of each proxy message, plus a 3 px amber (`#F0B15A`, `--amber`,
  `style.css`) left edge on the row and on the message.

## 1. One-time preparation (state-independent)

1. Do part 1 (steps 1 to 4) of `manual/personal-proxy-wiring-handoff.md`. In
   `config.toml` set `dry_run = false` and `confirmation_timeout_seconds = 120`
   in `[personal_proxy]`, and make sure `[journal]` does not set `enabled = false`.
2. Move the folder `journal` in the repository root away, so the sessions you
   look at are only the ones of this handoff.
3. Close any running Jarvis (`Ctrl+Alt+Q`).

## 2. The marker

1. Start: `python -m jarvis --status-console --personal-proxy`. Wait for the orb
   to read "Waiting for a request".
2. Say: "Расскажи коротко, что такое реле". Let the answer finish.
3. Open the Journal view (the "Journal" button in the top bar). Expected: one
   session row titled "Personal proxy session <date time>", with the arrow icon
   before the title and an amber stripe on its left edge. Hover the icon:
   the tooltip reads `Personal proxy: this goes to the external service`.
4. Select the row. Expected: the row gets its usual selection look (cyan border
   and tint) and keeps the amber left stripe and the icon; the stripe does not
   turn cyan and the tint does not turn amber.
5. In the feed Expected: each of the three events (request, sent, external
   answer) has the arrow icon at the start of its header and an amber left
   stripe, and keeps its own fill (the request cyan, the sent block amber tint).
6. Look at the icon at its real size. Report whether you can tell it from the
   other small icons and read it as "goes out" without the stripe (cover the
   stripe with a finger), and the other way round: whether the stripe alone is
   enough.

## 3. New context while idle

1. Still in the run of part 2, with the proxy idle (nothing spoken, no question).
   Type "черновик" into the Journal dock text box (do not send it).
   Press "New context". Expected: NO confirmation dialog appears. The blocks
   of the live chat in the Personal proxy panel are gone (the panel shows its
   empty text), the dock text box still holds "черновик". The dock status
   line reads `New session ready. Speak a request, or type it here.`; the session
   list still holds exactly one session (no empty session was added), now not the
   active one (its Delete button is enabled), and no row is selected; the feed
   shows `New session. It starts with your first request.`; the dock is active
   (since task v2.1.0-10c it takes a request while no live session exists).
2. Say: "Объясни, что такое диод". Let the answer finish. Expected: a second
   session row appears at once, marked like the first (select it to see its
   events); the first session did not gain any event.
3. Press `Ctrl+Alt+Q`. In PowerShell from the repository root:
   `Get-ChildItem journal` shows exactly two session folders; in
   `Get-Content -Encoding UTF8 journal\<first id>\events.jsonl` no line mentions
   "диод"; in the second folder's `events.jsonl` no line mentions "реле". There
   is no `"source":"context"` line in either (the action writes no event).

## 4. New context during a request

1. Start the run again (step 2.1). Say: "Расскажи подробно, как работает
   трансформатор, не меньше десяти предложений".
2. While the answer is still being spoken, press "New context". Expected: no
   confirmation dialog; the status line reads `A request is in progress or a
   question is waiting. Try again when it ends.`; the answer keeps playing to the
   end and is stored in the current session, and the live chat blocks of the
   Personal proxy panel are NOT cleared by the refusal.
3. After the answer finished, press "New context" again. Expected: accepted
   (`New session ready. Speak a request, or type it here.`).

## 5. New context during a pending question

1. Say a request that makes the proxy ask a question, for example: "Передай
   Марине Крыловой, что документы готовы". Expected: the proxy asks you to
   confirm and the Personal proxy panel (Status view) shows the heard text with
   the question. If it sends without asking, report that and use any request
   that makes it ask.
2. While the question is pending, open the Journal view and press "New context".
   Expected: the refusal text of part 4 step 2; the question stays pending.
3. Answer "нет" by voice. Expected: the request ends as not sent. Press
   "New context" again. Expected: accepted.
4. Press `Ctrl+Alt+Q`. In PowerShell: `Get-Content -Encoding UTF8
   journal\<session id>\events.jsonl` of the session of this part holds the heard
   request and a notice of the kind `not_sent`, and no `proxy_sent` line.

## 6. The normal mode is unchanged

1. Run `python -m jarvis --status-console` (no proxy flag). Say or type one
   short request, press "New context", accept the leave confirmation (it
   appears in normal mode). Expected: the
   status line reads `New context ready.`, a new session titled "New context"
   appears in the list at once, the proxy marker is nowhere in the window.
2. Press `Ctrl+Alt+Q`.

## 7. What to report

- Part 2: how the icon and the stripe look (size, contrast, whether either one
  alone is enough), and whether the selected row kept both.
- Part 3: whether the session list had one session after the button and two
  after the next request, and the `Get-ChildItem` result.
- Parts 4 and 5: the exact status line text when the button was refused, and
  whether the answer or the question was disturbed.
- Part 6: anything that differs from the normal behavior.
- Anything that differs from "Expected", with the text you saw.
