# Human-run verification handoff: generation length cap and truncated turns

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`
"Testing protocol"). Run by a human against live Ollama; the agent prepared it
and stops. Card: `tasks/done/task-generation-num-predict-cap.md` (moved to
`tasks/done/` on closure).

What this verifies: every request now carries a `num_predict` cap (default
16384); a dialog turn that hits it is visibly marked as cut off in the Journal
and in the conversation history, in text mode and in Text+voice mode; and a
dialog cap that does not fit the context window stops startup.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_generation_payloads.py`, `tests/test_config_generation.py`,
`tests/test_backend.py`, `tests/main_split/test_main_truncated_turn.py`,
`tests/main_split/test_main_mode3_second_pass.py`). This handoff checks the same
behavior end to end on the running app.

## Literal references used throughout

- Launch: `python -m jarvis --status-console --debug` from the repository root
  (`--debug` requires `--status-console`, `src/jarvis/app.py` `parse_args`; it
  writes the debug transcript). Never run two instances at once. Settings are
  read once at startup, so every `config.toml` edit below is made while Jarvis
  is shut down.
- Clipboard submit hotkey: `[hotkeys].clipboard_submit`, default `ctrl+alt+v`
  (`src/jarvis/core/config.py` `HotkeySettings.clipboard_submit`). It submits
  the current clipboard text as a question.
- Shutdown hotkey: `[hotkeys].shutdown`, default `ctrl+alt+q`
  (`HotkeySettings.shutdown`).
- If your `config.toml` `[hotkeys]` table sets either key to another value,
  press that value instead wherever this handoff names the default.
- Reasoning level and response mode are set by clicking the buttons on the
  Status tab (Status / Статус). Thinking mode (Режим мышления): Off / Low /
  Medium / High, in Russian UI Выкл / Низкий / Средний / Высокий. Response mode
  (Режим ответа): Text / Voice / Text+voice, in Russian UI Текст / Голос /
  Текст+голос (`src/jarvis/ui/status_console_ui/strings.js` `reasoning_*`,
  `mode_*`). Clicking a button selects that value directly, whatever the
  current state, so no starting state is assumed.
- Visibility: the top bar's toggle must be on Open (the Open / Hidden buttons,
  same labels in both UI languages, `index.html` `#visibilityToggle`). Click
  Open once after each launch; in Hidden the Journal tab shows only
  "Journal hidden (Hidden)" / "Журнал скрыт (Hidden)".
- Journal feed: Journal tab (Journal / Журнал), select the current session in
  the Sessions list on the left. The truncation label is
  `journal_outcome_truncated` in `strings.js`: EN
  "Cut off at the generation length limit.", RU
  "Обрезано: достигнут лимит длины генерации.". In Text+voice mode the spoken
  pass is a collapsed block under the reply labelled "spoken aloud" /
  "озвучено" (`journal_spoken_derivative_label`); a spoken pass cut at its own
  cap shows `journal_spoken_derivative_truncated`, the same EN / RU text as
  above, inside that block once expanded.
- Debug transcript: `<[logging].directory>/jarvis-debug.jsonl`; the directory
  defaults to `logs` (`LoggingSettings.directory` in config.py) and the file
  name is `TRANSCRIPT_FILE_NAME` in `src/jarvis/core/debug_transcript.py`.
  Read it with the checker (it finds the file for you):

  ```
  python -m manual.manual_check_generation_profiles --since SINCE
  ```

  It prints one block per model exchange at or after SINCE: `think=`, the
  first message, `options:` (the exact options sent, including
  `num_predict`), and `done_reason:` (`"length"` = stopped at the cap,
  `"stop"` = finished on its own).
- Engine log: `<[logging].directory>/jarvis.log` (`LOG_FILE_NAME` in
  `src/jarvis/core/log_config.py`). A request cut at the cap logs one line
  ending `WARNING jarvis.dialog.backend: Ollama request stopped at the length
  cap (num_predict=N)` (`OllamaBackend.iter_chat` in
  `src/jarvis/dialog/backend.py`).
- Effective caps: prints `num_ctx`, `prompt_capacity_tokens`, and the
  resolved `num_predict` of every request kind from your current config:

  ```
  python -c "from jarvis.core.config import load_settings; s = load_settings(); print(s.backend.num_ctx, s.history.prompt_capacity_tokens, {n: s.generation.options_for(n).num_predict for n in s.generation.profiles})"
  ```

- Setting a cap on a profile: in `config.toml`, find the table header named in
  the step (for example `[generation.dialog.off]`). If it exists, add the
  `num_predict = N` line directly under it (or change the value if the table
  already has a `num_predict` line). If it does not exist, append the header
  and the line at the end of the file. TOML rejects a table header written
  twice, so never add a second copy of an existing header. Removing a cap
  means deleting that `num_predict` line; if you created the table only for
  it, delete the header too.
- SINCE: before each launch, note the current local time as
  `YYYY-MM-DDTHH:MM:SS` (for example `2026-09-26T21:05:00`).

## Step 0 - baseline

0.1. Run the effective-caps command. Expect `65536 49152` (or your own
`num_ctx` and `prompt_capacity_tokens`) followed by every profile at
`16384`. If any profile shows another value, `config.toml` sets
`num_predict` somewhere: remove it (see "Setting a cap on a profile") and
rerun until every profile shows `16384`.

0.2. Count the truncation history note in the debug transcript so far:

```
python -c "import pathlib; p = pathlib.Path('logs/jarvis-debug.jsonl'); print(p.read_text(encoding='utf-8').count('Предыдущий ответ обрезан') if p.exists() else 0)"
```

Note the number as N0 (usually 0). Replace `logs` if `[logging].directory`
is set to another directory.

## Step a - a cut answer in Text mode, then "Продолжи"

a.1. Set `num_predict = 30` on `[generation.dialog.off]`. Run the
effective-caps command: `dialog.off` shows `30`, every other profile `16384`.

a.2. Note SINCE. Launch, click Open, wait for the warm-up to finish.

a.3. Status tab: click Thinking mode Off and Response mode Text. Copy
`Расскажи подробно историю Римской империи от основания Рима до падения Константинополя.`
and press `ctrl+alt+v`. Expect the answer to stop after a sentence or two,
mid-thought.

a.4. Journal feed: that answer shows the truncation label (EN or RU text
above).

a.5. Status tab: click Thinking mode Low (Низкий), which has no cap override.
Copy `Продолжи` and press `ctrl+alt+v`. Expect the answer to continue the
Roman history from roughly where it was cut, or to say that the previous
answer was cut off, rather than to treat the previous answer as complete.
This answer has no truncation label.

a.6. Press `ctrl+alt+q`. Run the step-0.2 command again. Expect a number
greater than N0 (the note was sent to the model with the history).

a.7. Run the checker with this SINCE. Expect, in order: the warm-up exchange
(`num_predict` 16384, `done_reason: "stop"`); the a.3 exchange (`think=False`,
`"num_predict": 30`, `done_reason: "length"`); the a.5 exchange
(`think='low'`, `"num_predict": 16384`, `done_reason: "stop"`).

a.8. `jarvis.log` has one length-cap warning with `num_predict=30` at the
a.3 time.

## Step b - Text+voice mode

b.1. Keep `[generation.dialog.off] num_predict = 30`. Note SINCE, launch,
click Open.

b.2. Status tab: click Thinking mode Off and Response mode Text+voice. Copy
the a.3 question and press `ctrl+alt+v`. Expect a cut text answer on screen,
then a spoken commentary over that partial text.

b.3. Journal feed: the reply shows the truncation label; its "spoken aloud" /
"озвучено" block, expanded, holds the spoken text and no truncation note.

b.4. Press `ctrl+alt+q`. Remove the `dialog.off` cap and set
`num_predict = 10` on `[generation.spoken_derivative]`. Effective caps:
`spoken_derivative` shows `10`, every other profile `16384`.

b.5. Launch (keep the b.1 SINCE), click Open. Status tab:
click Thinking mode Off and Response mode Text+voice. Copy
`Назови три планеты земной группы и коротко опиши каждую.` and press
`ctrl+alt+v`. Expect a complete text answer and speech that stops after a
few words.

b.6. Journal feed: the reply has no truncation label; its "spoken aloud" /
"озвучено" block, expanded, shows the short spoken text followed by the
truncation note (EN or RU text above).

b.7. Press `ctrl+alt+q`. Run the checker with SINCE (covers both launches).
Expect: b.2 first pass `think=False`, `"num_predict": 30`,
`done_reason: "length"`; b.2 spoken pass (first message starts
`system: Тебе передан точный текст`, the default
`[generation.spoken_derivative].prompt`, `_DEFAULT_RESPONSE_TEXT_VOICE_CONTRACT`
in config.py, unless your config sets that prompt) `"num_predict": 16384`,
`done_reason: "stop"`; b.5 first pass `"num_predict": 16384`,
`done_reason: "stop"`; b.5 spoken pass `"num_predict": 10`,
`done_reason: "length"`. Warm-up exchanges show 16384 and `"stop"`.

b.8. `jarvis.log` has length-cap warnings with `num_predict=30` (b.2) and
`num_predict=10` (b.5).

## Step c - reasoning spends the whole cap (the empty-answer case)

c.1. Remove the `spoken_derivative` cap. Set `num_predict = 200` on
`[generation.dialog.medium]`. Effective caps: `dialog.medium` shows `200`,
every other profile `16384`.

c.2. Note SINCE, launch, click Open. Status tab: click Thinking mode Medium
(Средний) and Response mode Text. Copy
`Напиши сонет о море, в котором каждая строка начинается на букву М.` and
press `ctrl+alt+v`.

c.3. Expect within a few seconds an empty (or nearly empty) answer, and in the
Journal feed the truncation label with an empty or near-empty body.

c.4. Press `ctrl+alt+q`. Checker: the c.2 exchange shows `think='medium'`,
`"num_predict": 200`, `done_reason: "length"`.

This step is probabilistic: the model may finish its reasoning and a short
answer within 200 tokens. If the checker shows `done_reason: "stop"`, repeat
c.2-c.4 once; if it is still `"stop"`, report the checker block and the
answer text rather than treating it as a failure.

## Step d - no overrides: every request carries 16384

d.1. Remove the `dialog.medium` cap. Effective caps: every profile shows
`16384` (as in 0.1).

d.2. Note SINCE, launch, click Open, wait for the warm-up. Status tab: click
Thinking mode Off and Response mode Text; copy
`Сколько будет 17 умножить на 23?` and press `ctrl+alt+v`. Then click
Thinking mode Medium (Средний) and repeat. Then click Thinking mode Off and
Response mode Text+voice; copy `Назови три планеты земной группы.` and press
`ctrl+alt+v`; wait until the speech ends. Press `ctrl+alt+q`.

d.3. Checker: every exchange (warm-up, the three dialog turns, the spoken
pass) shows `"num_predict": 16384` in `options`, with every other option
unchanged from before this change, and `done_reason: "stop"`. No
truncation label in the Journal feed for these turns.

## Step e - a dialog cap that does not fit the context window

e.1. Set `num_predict = 20000` on `[generation.dialog.high]`. This must make
`prompt_capacity_tokens + 20000` exceed `num_ctx` (the two numbers printed in
0.1; with 49152 and 65536, 69152 > 65536). If your `num_ctx` is larger, use a
value above `num_ctx - prompt_capacity_tokens` instead of 20000.

e.2. Run:

```
python -c "from jarvis.core.config import load_settings; load_settings()"
```

Expect a traceback whose last line is (from `_validate_settings` in
`src/jarvis/core/config.py`):

`jarvis.core.config.ConfigError: [history].prompt_capacity_tokens plus the largest dialog cap [generation.dialog.high].num_predict (20000) must fit backend.num_ctx: 69152 > 65536`

(the two numbers after the colon are `prompt_capacity_tokens + 20000` and
your `num_ctx`).

e.3. Run the launch command. Expect it to exit before any window opens, with
the same last line.

e.4. Remove the `dialog.high` cap. The e.2 command prints nothing and raises
nothing.

## What to report back

For each step, the checker output (a.7, b.7, c.4, d.3), the step-0.2 counts
(N0 and a.6), and one line on what the Journal feed showed (a.4, b.3, b.6,
c.3) and what "Продолжи" produced (a.5); for step e, the last line of the
traceback. Or the first step whose result differs from the expectation, with
its output.
