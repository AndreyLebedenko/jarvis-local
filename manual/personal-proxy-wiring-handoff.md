# Human-run handoff: personal proxy application wiring (task v2.1.0-9b)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by
a human: it needs the microphone, the speakers, the GPU, the live local Ollama
endpoint and (for part 4 only) an OpenAI-compatible chat endpoint of your
choice. The agent prepared it and ran none of it.

What it answers: with `--personal-proxy`, does a spoken or typed message run the
whole pipeline (heard, question, sent, answer shown and spoken); does the
`Ctrl+Alt+I` interrupt behave as designed; is the microphone always given back;
are the controls of the main model refused; does a failed start keep the window
open with a reason and start nothing.

Documentation debt, stated on purpose: the user documentation of the whole
feature (README, config guide) is task v2.1.0-12 and does not exist yet. This
handoff does not rely on it; every key, command and default it needs is named
below with its source file.

Automated counterpart already green: `python -m pytest` (includes
`tests/main_split/test_main_personal_proxy.py`,
`tests/test_personal_proxy_assembly.py`, `tests/test_personal_proxy_runtime.py`,
`tests/test_personal_proxy_ui.py`, `tests/test_ui_transport_personal_proxy.py`).

## Literal references

- Every command runs from the repository root, in the environment where
  `python -m jarvis` normally runs (the one where `pip install -e .` was done,
  README.md "Manual installation"). Jarvis reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`) and, next to it,
  `config.ui.toml`; a key that is absent means the code default.
- Start command (`parse_args` in `src/jarvis/app.py`):
  `python -m jarvis --status-console --personal-proxy`. `Jarvis.cmd` adds
  `--status-console` itself, so `Jarvis.cmd --personal-proxy` is the same run.
  The flag needs `--status-console` and excludes `--mcp-mode` and `--debug`
  (`parse_args`, `src/jarvis/app.py`; `--debug` records the model exchange, which
  in this mode would hold the transcript and the answer).
- `[personal_proxy]` keys used (defaults in `PersonalProxySettings`,
  `src/jarvis/core/config.py`; commented in `config.example.toml`):
  `endpoint` (default `""`, must be set), `model` (default `""`, must be set),
  `api_key_env` (default `"JARVIS_PERSONAL_PROXY_KEY"`, the NAME of the
  environment variable that holds the key), `dry_run` (default `true`),
  `topics_file` (default `"personal_proxy_topics.txt"`, relative to the working
  directory), `confirmation_timeout_seconds` (default `20`),
  `doubt_min_listed` (default `1`), `check_model` (default `"gemma4:12b"`),
  `check_num_ctx` (default `8192`), `stt_device` (default `"cuda"`).
- Hotkeys (`HotkeySettings`, `src/jarvis/core/config.py`; overridable in the
  `[hotkeys]` section of `config.toml`; check that section first and use the
  bindings it shows if it overrides any):
  shutdown `Ctrl+Alt+Q` (`shutdown`), interrupt `Ctrl+Alt+I` (`interrupt`),
  microphone sleep `Ctrl+Alt+M` (`mic_sleep_toggle`). In this mode these three
  are the only bound ones. `Ctrl+Alt+S` and `Ctrl+Alt+R` (screenshots),
  `Ctrl+Alt+V` (clipboard), `Ctrl+Alt+T` (thinking) and `Ctrl+Alt+O` (response
  mode) are deliberately NOT bound; pressing them must do nothing. The list of
  what is bound is `_personal_proxy_background_work` in `src/jarvis/app.py`.
- The question after a doubt, the answer vocabulary and the offer texts are in
  `src/jarvis/personal_proxy/confirmation_texts.py` and
  `confirmation_vocabulary.py`; only a whole-answer clear yes sends.
- The window text and the events panel are in the language of `[ui].language`
  (default `"en"`, `UiSettings`); this handoff names the English texts.

## 1. One-time preparation (state-independent)

1. Speech engine: `python -m pip install -r requirements-stt.txt`, then
   `python setup_stt_model.py` once (network needed once; it caches
   `large-v3-turbo`). Expected last line: "Done. The model is cached locally".
2. Ollama is running at `[backend].endpoint` (default `http://localhost:11434`,
   `BackendSettings`) and the check model is installed:
   `ollama pull gemma4:12b` (the value of `[personal_proxy].check_model`). Check:
   `ollama list` shows `gemma4:12b`.
3. Open `config.toml` and make the `[personal_proxy]` section contain exactly
   these keys (write every one, do not rely on a remembered default):
   ```
   [personal_proxy]
   endpoint = "http://localhost:11434/v1/chat/completions"
   model = "gemma4:12b"
   api_key_env = "JARVIS_PERSONAL_PROXY_KEY"
   dry_run = true
   topics_file = "personal_proxy_topics.txt"
   confirmation_timeout_seconds = 20
   doubt_min_listed = 1
   ```
   `endpoint` here is Ollama's own OpenAI-compatible route, used only as a
   harmless stand-in for the external model: the endpoint rule allows `http` on
   `localhost` (`require_secure_endpoint`, `external_endpoint.py`), so no
   real provider and no key is needed for this handoff. Expected, not verified
   by the agent: Ollama answers `/v1/chat/completions` with a stream and ignores
   the key. If you prefer a real provider, set `endpoint` (https) and `model` to
   its values and use your real key in step 4; nothing in this handoff needs it.
4. In the terminal that starts Jarvis, set the key variable to any printable
   ASCII text (PowerShell): `$env:JARVIS_PERSONAL_PROXY_KEY = "handoff-test"`.
   The name must equal `api_key_env`.
5. A Journal session with an assistant reply (needed only by step 5.2; it makes
   that step independent of what the Journal held before). `[journal].enabled`
   is `true` by default (`JournalSettings`, `src/jarvis/core/config.py`; check
   `config.toml` does not set it to `false`). Start a NORMAL run, which uses the
   main model `[backend].model`: `python -m jarvis --status-console`; wait for
   the orb to read "Waiting for a request"; type "Привет" in the Journal view
   dock and press Send; wait until Jarvis has answered; press `Ctrl+Alt+Q`.
6. Close any running Jarvis (`Ctrl+Alt+Q`) and any other GPU-heavy program.

## 2. Start and the idle state

1. `python -m jarvis --status-console --personal-proxy`
2. Expected: the Status Console window opens; the orb shows "Warming up the
   model..." (a generic text: in this mode it covers the speech engine and the
   check model, never the main model; this can take tens of seconds on the first
   run), then "Waiting for a request", and the "listening" cue sounds once. The
   top bar shows the badge "PERSONAL PROXY" and the model name from
   `[personal_proxy].model` (`gemma4:12b` after step 1.3), NOT `[backend].model`.
   The backend chip reads "check model ready" (it never reads "responding" in
   this mode). The events panel shows "Personal proxy ready: the check model is
   warmed up" from the source PERSONAL_PROXY, no "Model warm-up complete" and
   no error.
3. In a second terminal: `ollama ps`. Expected: `gemma4:12b` is loaded; its
   context is 8192 (the `check_num_ctx` variant), not 65536.
4. Expected in the window: the "Personal proxy" panel with an input box under the
   modules row; the Thinking and Response mode cards are greyed out.
5. Press `Ctrl+Alt+S`, `Ctrl+Alt+V`, `Ctrl+Alt+T`, `Ctrl+Alt+O`. Expected: nothing
   happens (no screenshot cue, no mode change, no event).
6. Close it (`Ctrl+Alt+Q`), then run
   `python -m jarvis --status-console --personal-proxy --debug`. Expected: no
   window; the terminal prints "--personal-proxy cannot be combined with --debug"
   and the process exits with code 2 (`echo $LASTEXITCODE` in PowerShell). No
   debug transcript file is written. Then start again with step 2.1.

## 3. Dry run (config as in step 1.3: `dry_run = true`)

1. Say, at normal volume: "Позвони Марине Крыловой по номеру восемь девятьсот
   двенадцать триста сорок пять шестьдесят семь восемьдесят девять".
2. Expected, in the Personal proxy panel: ONE block "Dry run - nothing was sent"
   with the speech engine text, the checked text, the doubts, "Would ask" yes
   or no, the sanitized text with placeholders such as `<PERSON_1>`, the
   mapping (stays local), the verdict, the outbound gate result and the exact
   payload. No question is spoken, no "Heard" block, nothing is spoken at all,
   and the locality badge stays "Local". Report what the block shows for the
   gate (a phone number left in the sanitized text must show as blocked).
3. Type "Расскажи коротко, что такое реле" in the panel's input box and press
   Send. Expected: a dry-run block whose "Speech engine text" is empty (typed
   text skips the speech stage) and whose payload holds your sentence.
4. Say nothing but make a noise (tap the desk) for a second. Expected: no block
   or a single notice "Nothing to send: no speech or text was recognized."; the
   speech engine is not asked (silence and noise are kept away from it).

## 4. Sending (set `dry_run = false`, restart with step 2.1)

The stand-in endpoint of step 1.3 answers; the locality badge is the check.

1. Say: "Расскажи коротко, что такое реле". Expected, in order: a "Heard" block
   (decision "Sending without a question" when no doubt was found), a "Sent to
   the external model" block that equals what you would have seen in the dry
   run payload, then "Answer (external model)" sentences appearing one by one
   and spoken aloud, one sentence at a time. While the answer streams the badge
   reads "External backend" and returns to "Local" at the end.
2. With a doubt. Say a request with an e-mail address spelled letter by letter,
   for example: "Напиши письмо на адрес i v a n p e t r o v собака g m a i l
   точка c o m". The judge lists doubts on roughly 13 of 60 recordings of the
   spike corpus (`PROJECT.md`, "Confirmation exchange"), so a question is not
   certain; try another phrase if none comes. When the question comes:
   - a "Heard" block with decision "Asking you to confirm before sending" shows
     the WHOLE heard text; a voice names what to check; the microphone is off
     while it speaks and on again after.
   - 2a. Answer by voice "да". Expected: sent as in step 4.1.
   - 2b. Repeat and answer "нет". Expected: nothing is sent; the offer to correct
     by text or dictate again is spoken and shown; no "Sent" block.
   - 2c. Repeat and stay silent for 20 seconds (`confirmation_timeout_seconds`).
     Expected: same as 2b, nothing sent.
   - 2d. Repeat and type "да" in the panel's input box (typed text is the
     answer while a question waits). Expected: sent.
   - 2e. Repeat and, while the question waits (before you answer), click
     "Hidden" in the top bar's Open/Hidden switch (`data-mode="hidden"` in
     `src/jarvis/ui/status_console_ui/index.html`). Expected: nothing is sent
     (the question ends as "no"), the offer text is NOT shown, the Personal
     proxy panel is cleared. Click "Open": the panel is empty, no "Sent" block
     appears, and the next thing you say is a new request.
5. Interrupt. `Ctrl+Alt+I` is `[hotkeys].interrupt`:
   - 5a. During a question (step 4.2): press `Ctrl+Alt+I`. Expected: the
     question ends as "no" (nothing sent, the offer is shown), and the next
     thing you say is a new request.
   - 5b. While the answer is being spoken: press `Ctrl+Alt+I`. Expected: the
     speech stops at once, a notice "The request was interrupted." appears, the
     badge returns to "Local", and the next thing you say is heard (the
     microphone was given back). Say a short request to prove it.
   - 5c. Right after you finish speaking, while the stages still work (before
     any "Sent" block): press `Ctrl+Alt+I`. Expected: the notice and no "Sent"
     block, nothing reaches the endpoint.
6. Microphone sleep: press `Ctrl+Alt+M`. Expected: the sleep cue; the next
   utterance is ignored. Press `Ctrl+Alt+M` again: the wake cue; the next
   utterance is a request.
7. Mute: turn the speech switch off in the window (TTS). Run step 4.1. Expected:
   the text appears and nothing is spoken; the microphone still comes back.
8. Two requests in a row: say a request, and without waiting say a second one
   while the first is being answered. Expected: the second is queued and runs
   after the first (never two "Sent" blocks open at once).

## 5. Refused controls (dry_run either way)

1. In the window, the Thinking level buttons, the Response mode buttons and (in
   the Journal view) "New context" and the fork button are greyed out.
2. Journal view, the session from step 1.5 (it has an assistant reply): use its
   replay control (the "Play" speaker button on the assistant reply). Expected:
   nothing plays, and the Status view's events panel gains a warning "Personal
   proxy mode: this control is not available". (Replay, transcript generation,
   annotation generation and consolidation execution are refused here; these
   buttons are not greyed out, so this is the way to reach the refusal message.
   Consolidation execution is only refused; nothing in this mode sends it to a
   model.) If the session list is empty, step 1.5 was not done.
3. Journal view dock: the text box and the attach button are disabled, and the
   dock shows "In the personal proxy mode, type requests in the Personal proxy
   panel of the Status view." Type the request in that panel instead (step 3.3
   does it). Attachments cannot be offered in this mode; the server's reply to
   a direct upload ("Attachments are not available in this mode.") is covered by
   `tests/main_split/test_main_personal_proxy.py`, not by this handoff.

## 6. Startup failures (the window must stay open)

For each case below: start with step 2.1, expect the window to open, the orb to
show "Error" with the reason, the events panel to show an ERROR line from the
source PERSONAL_PROXY, the microphone chip not to show "listening", no
"listening" cue to sound, the backend chip not to read "responding" or "check
model ready", and `Ctrl+Alt+Q` to close it. The reason must name only the key or the action, never
a path or a text of yours. Restore the setting afterwards.

- 6a. `topics_file = "no_such_topics_file.txt"` in `[personal_proxy]`. Expected
  reason: the topics file cannot be used, see `[personal_proxy].topics_file`.
- 6b. In the starting terminal: `Remove-Item Env:JARVIS_PERSONAL_PROXY_KEY`.
  Expected reason: the API key variable is missing or unusable.
- 6c. `endpoint = "http://example.com/v1"`. Expected reason: the endpoint must
  be https or a local http address.
- 6d. `check_model = "no-such-model"`. Expected reason: the check model is not
  installed in Ollama.
- 6e. Stop Ollama, then start. To stop it on Windows: right-click the Ollama icon
  in the notification area and choose "Quit Ollama", then in PowerShell run
  `Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force`
  (removes the tray app "ollama app" and the server "ollama" if any is left) and
  check that `ollama list` now fails with a connection error. Expected reason:
  Ollama is not reachable. To restore it afterwards, start "Ollama" from the
  Start menu (or run `ollama serve` in a spare terminal) and check that
  `ollama list` works again.
- 6f. `endpoint = ""` (or `model = ""`). Expected: no window; the terminal prints
  the missing key and the process exits with code 5 (`PERSONAL_PROXY_STARTUP_FAILED_EXIT_CODE`
  in `src/jarvis/app.py`). Check with `echo $LASTEXITCODE` (PowerShell).
- In every case also check: speaking does nothing, no "Sent" block, and typing
  a request in the Personal proxy panel and pressing Send shows under the input
  the SAME reason text as the events panel (for example "Personal proxy not
  started: Ollama is not reachable at [backend].endpoint"), not "The request
  queue is full".

## 7. The tray launcher

The tray launcher (`JarvisLauncher.cmd`, `src/jarvis/launcher/runtime.py`) has
only the modes "assistant" and "mcp" (`--mode` choices); it cannot start the
personal proxy, so its visibility of this mode's failures cannot be checked and
is reported as a gap. Check only: start `JarvisLauncher.cmd`, open its menu and
confirm that no personal proxy mode is offered. A failure that exits before the
window (case 6f, exit code 5) is visible only in a terminal, which is why the
other failures keep the window open with the reason.

## 8. Shutdown

1. While idle press `Ctrl+Alt+Q`. Expected: the window closes and the process
   exits promptly; `ollama ps` may still list the model (Ollama's own keep-alive).
2. Start again, begin an answer (step 4.1) and press `Ctrl+Alt+Q` while it is
   spoken. Expected: speech stops, the process exits, no traceback in the
   terminal.
3. Search the newest log under `logs/` (`[logging]` section, `LoggingSettings`):
   it must contain no sentence you said, no heard text, no sanitized text and no
   answer text (only counts, kinds and fixed messages). Report any line that does.

## What to report

For each step: what you saw against what is expected above, in your words and
the exact text of any notice or error. Severity matters: report first anything
that was SENT that should not have been (a "Sent" block after a "no", silence,
timeout or interrupt), anything spoken or shown that holds a value from the
mapping in a log line, a microphone that stayed off, and a started proxy after
a failed validation.
