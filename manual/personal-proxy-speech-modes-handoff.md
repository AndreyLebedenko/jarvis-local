# Human-run handoff: personal proxy speech modes, v2.1.1 (task v2.1.1-6)

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`). Run by a human: it
needs the speakers, the microphone (only for the optional step 2.4), the GPU and the live
local Ollama endpoint. The agent prepared it and ran none of it. It does not depend on any
other handoff; every key, hotkey, command and default it needs is named below with its
source. The user documentation it relies on is the subsection "Response modes in the proxy"
of `README.md` (English) and `README.ru.md` (Russian).

What it answers, for `--personal-proxy`: (1) do the hotkey and the Status tab buttons change
the response mode in proxy mode; (2) does Text still send the default system prompt and speak
every sentence as received; (3) does Voice send the voice paragraph and speak cleaned
sentences while the screen shows the answer as received; (4) does Text+voice speak only after
the whole answer, from the local spoken version, and fall back when that pass fails; (5) does
the Journal record the mode and the spoken version; (6) what is the latency of Text+voice on a
long answer.

Privacy: no real provider and no real key is needed. The "external" model is Ollama itself on
this machine (step 1.2). Use only invented text. Your Journal will hold the heard and typed
texts of this run whole (by design); delete the test sessions afterwards if you want
(Journal view, session menu "...").

Automated counterpart already green: `python -m pytest`, `ruff check`, `ruff format --check`.

## Literal references

- Every command runs from the repository root. Jarvis reads `config.toml` from the current
  directory (`DEFAULT_CONFIG_PATH`, `src/jarvis/core/config.py`); a key that is absent means
  the code default (`config.example.toml` comments every key).
- Start command (`parse_args`, `src/jarvis/app.py`):
  `python -m jarvis --status-console --personal-proxy`. The flag needs `--status-console` and
  excludes `--mcp-mode` and `--debug`.
- `[personal_proxy]` keys (defaults in `PersonalProxySettings`, `src/jarvis/core/config.py`):
  `endpoint` (default `""`, required), `model` (default `""`, required), `api_key_env`
  (default `"JARVIS_PERSONAL_PROXY_KEY"`, the NAME of the environment variable that holds the
  key), `dry_run` (default `true`), `spoken_pass_timeout_seconds` (default `30`, added in
  v2.1.1), `check_model` (default `"gemma4:12b"`), `check_num_ctx` (default `8192`).
- `[response].mode` (`ResponseSettings.mode`, default `"text"`) is the mode at start. The
  Settings tab drop-down "Response mode" writes `config.ui.toml` and can override it, so this
  handoff never relies on the starting mode: step 2.2 sets the mode by clicking.
- Response-mode hotkey (`HotkeySettings.response_mode_toggle`, `src/jarvis/core/config.py`,
  default `Ctrl+Alt+O`; overridable in `[hotkeys]` of `config.toml`; if that section overrides
  it, use the binding it shows): each press cycles Text -> Voice -> Text+voice -> Text. Other
  bound hotkeys in this mode: shutdown `Ctrl+Alt+Q`, interrupt `Ctrl+Alt+I`, microphone sleep
  `Ctrl+Alt+M`.
- The Status tab has a group "Response mode" with three buttons "Text", "Voice" and
  "Text+voice" (`src/jarvis/ui/status_console_ui/strings.js`, English; the window text follows
  `[ui].language`, default `"en"`). Clicking one selects that mode for the live session.
- The Journal dock (typing a request) is in the Journal view; the "Sent" block folds the
  standard system prompt behind the label "Standard system prompt (click to show)".
- Journal events are in `journal/<session>/events.jsonl` (`[journal].root`, default
  `"journal"`, `src/jarvis/journal/store.py`). The proxy answer event has `source`
  `"proxy_answer"`; its `metadata` holds `response_mode` and, for Text+voice when the local
  pass worked, `spoken_derivative`.
- The voice paragraph (`VOICE_SYSTEM_PROMPT`, `src/jarvis/personal_proxy/common/payload.py`)
  starts with the standard system prompt and adds: "The answer will be read aloud: write plain
  prose without Markdown, lists, tables, headings or emphasis, and write abbreviations, units
  and symbols as full words."

## 1. One-time preparation (state-independent)

1. Ollama is running at `[backend].endpoint` (default `http://localhost:11434`) and
   `ollama list` shows `gemma4:12b` (`ollama pull gemma4:12b` otherwise). Speech recognition
   (`requirements-stt.txt`, `setup_stt_model.py`) is needed only for the optional step 2.4.
2. Make the `[personal_proxy]` section of `config.toml` contain exactly these keys:

   ```
   [personal_proxy]
   endpoint = "http://localhost:11434/v1/chat/completions"
   model = "gemma4:12b"
   api_key_env = "JARVIS_PERSONAL_PROXY_KEY"
   dry_run = false
   spoken_pass_timeout_seconds = 30
   ```

   `endpoint` is Ollama's own OpenAI-compatible route, a stand-in for the external model.
   Nothing leaves the machine. `dry_run = false` is needed: a dry run sends nothing.
3. In the terminal that starts Jarvis (PowerShell):
   `$env:JARVIS_PERSONAL_PROXY_KEY = "handoff-test"`.
4. Close any running Jarvis (`Ctrl+Alt+Q`) and any other GPU-heavy program.

## 2. Start and the mode control

1. `python -m jarvis --status-console --personal-proxy`. Expected: the Status Console opens,
   the badge "PERSONAL PROXY" shows, the orb reaches "Waiting for a request".
2. In the Status tab click "Text" in the group "Response mode". Expected: "Text" is
   highlighted. Click "Voice", then "Text+voice": each becomes the highlighted one and the
   events panel shows no "refused" warning (before v2.1.1 this control was refused here).
3. Click "Text". Press `Ctrl+Alt+O` once. Expected: "Voice" is highlighted. Press it again:
   "Text+voice". Again: "Text". Report any press that changes nothing.
4. Optional (microphone): say any short Russian sentence in each mode and confirm a request
   starts. Skip it if you only type.

## 3. Text mode

1. Click "Text". Type in the Journal dock and press Send:
   "Перечисли по пунктам, сколько тысяч человек было в армии Наполеона в 1812 г. и какая была
   температура в ноябре, °C".
2. Expected: a "Sent" block (the system prompt folded behind "Standard system prompt (click to
   show)"; unfold it: it is exactly the two sentences "Answer in the language of the request.
   Keep placeholders such as <PERSON_1> exactly as written."), then "Answer (external model)"
   sentences, spoken one by one as received (a reply with list marks or "**" is read with
   them; abbreviations such as "тыс." are read as written). This is the unchanged v2.1.0
   behavior.

## 4. Voice mode

1. Click "Voice". Type the same request as in 3.1.
2. Expected: the unfolded system prompt of the "Sent" block now also holds the voice paragraph
   quoted in "Literal references". The screen shows the answer as received (it may still hold
   list marks or abbreviations; that is the model's own output). What is spoken has no Markdown
   sounds, and "тыс.", "млн", "°C", "г." after a number are spoken as words ("тысяч",
   "градусов Цельсия", "года"). Speech starts while the answer is still streaming. Report one
   sentence that was shown with a marker or an abbreviation and how it was spoken.
3. Type: "Расскажи про XX век в двух предложениях". Expected: "XX век" is spoken as "двадцатый
   век" (the case follows the next word).

## 5. Text+voice mode

1. Click "Text+voice". Type the same request as in 3.1. Note the time T0 of pressing Send.
2. Expected: the "Sent" block shows the standard system prompt (no voice paragraph); the answer
   sentences appear on the screen as received while nothing is spoken; after the last sentence
   there is a pause (the microphone is paused, the local pass runs), then the answer is
   spoken in a form that sounds like a retelling (it may refer to the screen). Note the time T1
   when speech starts: the latency is T1 - T0 minus the time the answer took to stream. For a
   long answer (ask for about 400 words) report T1 - T0. Speech must not start before the
   last sentence is on the screen.
3. Fallback: in `config.toml` set `spoken_pass_timeout_seconds = 0.001`, restart (2.1), click
   "Text+voice", send the request again. Expected: the same pause is very short and the
   answer is spoken cleaned, sentence by sentence, as in Voice. Restore the value `30` and
   restart afterwards.
4. Interrupt: send a long request in "Text+voice", and press `Ctrl+Alt+I` while the pause
   before speech lasts. Expected: nothing is spoken, the microphone is back.

## 6. Mode latching and the Journal

1. Click "Text+voice", send a long request, and while the answer is still streaming click
   "Text". Expected: the running request stays in Text+voice (the spoken pass still happens);
   the next request is in Text.
2. After a request in each of the three modes, in PowerShell from the repository root:

   ```powershell
   Get-ChildItem journal -Recurse -Filter events.jsonl | Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { Get-Content -Encoding UTF8 $_.FullName } | Select-String '"source":\s*"proxy_answer"'
   ```

   Expected: each `proxy_answer` line holds `response_mode` `text`, `voice` or `text_voice`;
   only a Text+voice line whose local pass worked also holds `spoken_derivative`. The event
   `text` is the answer as shown.
3. In the Journal view open the Text+voice session. Expected: the answer shows a collapsed
   "spoken aloud" block with the spoken version.

## Report back

For each of the sections 2-6: pass or the exact deviation (what you expected, what happened).
For 5.2 the latency in seconds. Whether anything in the README subsection "Response modes in
the proxy" contradicted what you saw.
