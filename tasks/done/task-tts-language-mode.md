# Task: TTS language mode

Status: Completed. Manual handoff passed (owner, 2026-09-28).

## Summary

A Settings option chooses how TTS picks the speech language:

1. `dynamic` - today's behavior: each Cyrillic/Latin run is voiced by its own
   language route.
2. `request` - the whole spoken answer is voiced in one language, the
   language of the request.
3. `ru` / `en` - the whole spoken answer is asked for in that language.

In modes 2-3 the language is passed to the model with the request, so it
writes text that one voice can pronounce: in response mode `voice` (the
single pass) and in the second (spoken-derivative) pass of `text_voice`.
The first pass of `text_voice` gets no language directive; the canvas stays
untouched. Response mode `text` ignores the option entirely.

## Decisions (owner, 2026-09-28)

- `request` is hybrid. A typed request (text input, clipboard, attachment
  typed text) gets its language detected and the model is told it
  explicitly. A voice request has no transcript before dispatch: the model
  is told to answer in the language of the question. The `text_voice`
  second pass always gets an explicit language: the language of the
  first-pass canvas.
- Language detection: Russian if any Cyrillic letter appears outside code
  spans, else English if any Latin letter does. Built so the language source
  can later become the dialog (session) language, i.e. the language of the
  previous answer: the resolver takes an already detected language.
- The language directive in the prompt is a hint, weaker than the user
  explicitly asking "answer in <language>". Consequently the voice follows
  the language the answer is actually written in (its first sentence with
  letters); the requested language only voices sentences before that.
- Fixed `ru`/`en`: the spoken text is written in that language unless the
  user explicitly asks otherwise; foreign names and terms go into that
  language's script.
- Response mode `text` keeps `dynamic` whatever the setting.
- Applied from Settings, restart-to-apply (`[tts].language_mode` in
  `config.ui.toml`). The orchestrator reads the mode per turn; a later live
  toggle replaces the constructor value with a runtime state owner.

## Boundary

- In scope: config key and validation, the three language directives
  (`[response].speech_language_ru|en|request`), per-pass directive on
  `ModelRequestStarted`, single-language unit buffering in `TtsOutput`,
  Settings form field, `speech=` tag on the model-request log line,
  PROJECT.md.
- Out of scope: a live toggle; the dialog-language source; journal reply
  replay (stays charset-routed); changing route coverage validation.
- Known gap: mode 3's second pass sees only the canvas, not the user's
  request, so under fixed `ru`/`en` it cannot notice an explicit user
  request for another language.

## Acceptance criteria

- `dynamic` (default) prompts and routing are unchanged. The one visible
  difference: a partial sentence left by a pass that never completed is no
  longer prepended to the next turn's speech.
- In `ru`/`en`/`request` (modes `voice`/`text_voice`), every unit of a spoken
  answer reaches one language route; no language-switch unit splits.
- Mode `voice` appends the matching language directive after the voice
  contract; the `text_voice` second pass appends it after the
  spoken-derivative prompt; mode `text` and the first pass get none.
- Settings shows and saves the option; invalid values are rejected at
  config load and at save.
- Automated tests green (`python -m pytest`, `ruff check`, `ruff format
  --check`); a manual handoff is prepared for live voice verification.

## Manual handoff (human-run: live Ollama, speakers, microphone)

Sources for every name below: UI labels are the English strings in
`src/jarvis/ui/status_console_ui/strings.js` (the Russian UI shows their
translations); hotkey defaults are in `src/jarvis/core/config.py`
(`HotkeySettings`) and `config.example.toml` `[hotkeys]`.

Preconditions:

- Distinct ru and en voices. Settings view -> "Speech synthesis (TTS)" ->
  "Configure per-language voices" must be checked, with "Voice (ru)" and
  "Voice (en)" showing different engines or models (for example silero /
  piper). Unchecked means the Silero-only default, which voices both
  languages with the Russian voice and cannot show the difference.
- Start Jarvis with `Jarvis.cmd` (README, "Usage"). Each model request
  writes one `[LLM] Model request: ...` line to the file system log, in the
  directory `[logging].directory` (default `logs`, `LoggingSettings` in
  `src/jarvis/core/config.py`; the newest file there). The events panel
  shows a localized entry without the tag, so read the file. The `speech=`
  tag is the language asked of the model: `speech=ru`, `speech=en`,
  `speech=from-answer`, or no tag for `dynamic`.

Per step, in this order:

1. Settings view -> "Speech synthesis (TTS)" -> "Speech language" -> pick the
   step's value -> "Apply". Check that `config.ui.toml` now has
   `language_mode = "<value>"` under `[tts]`.
2. Close Jarvis and start it again with `Jarvis.cmd` (restart-to-apply).
3. After the restart, Status view -> "Response mode" card -> click the
   step's button ("Voice" or "Text+voice") directly. Do this after the
   restart: a restart starts in the Settings form's "Response mode" value.
   Do not use `Ctrl+Alt+O` (`response_mode_toggle`), which cycles and so
   depends on the current mode.
4. Typed requests: Journal view -> "Message Jarvis" box -> "Send". Voice
   requests: just speak - the microphone starts awake after every start
   (`AudioInput._user_wants_awake = True`, `src/jarvis/audio/input.py`); do
   not press `Ctrl+Alt+M` (`mic_sleep_toggle`), which would put it to sleep.

Steps:

1. "Always English" + "Voice": say a question in Russian. Expected: log
   `speech=en`; the answer is in English, spoken by the English voice only.
2. "Always Russian" + "Voice": type `What is a WebSocket?`. Expected: log
   `speech=ru`; the answer is in Russian, spoken by the Russian voice only,
   including any English term.
3. "Always Russian" + "Voice": type `Answer in English: what is a
   WebSocket?`. Expected: the explicit request wins - the answer is in
   English and spoken by the English voice only.
4. "Language of the request" + "Voice": type `What is a WebSocket?`, then
   `Что такое WebSocket?`. Expected: `speech=en` then `speech=ru`; the first
   answer all English voice, the second all Russian voice, including the
   word WebSocket.
5. "Language of the request" + "Voice": say a question in English, then one
   in Russian. Expected: `speech=from-answer` both times; each answer is in
   the question's language and voiced by that one voice throughout.
6. "Language of the request" + "Text+voice": type `Сравни TCP и UDP в
   таблице`. Expected: two log lines, the second with `pass=derivative
   speech=ru`; the spoken part (Journal: expand "spoken aloud" under the
   answer) is Russian and voiced by the Russian voice only.
7. "Always English" + "Text+voice": type `Сравни TCP и UDP в таблице`.
   Expected: the screen canvas may be in Russian; the second log line has
   `pass=derivative speech=en`; the spoken part is English, English voice
   only.
8. "Always English" + "Text": type `Что такое WebSocket?`. Expected: no
   `speech=` tag; today's behavior - Russian voice for Russian text,
   English voice for `WebSocket`.
9. "Auto-detect answer language" + "Voice": type `Что такое WebSocket?`. Expected: no
   `speech=` tag; today's behavior as in step 8.

Report per step: pass/fail and, on fail, the log line, the answer text from
the Journal, and which voice was heard.
