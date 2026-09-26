# Human-run verification handoff: generation profiles

Executable from its own text, per Testing protocol item 4 (`CLAUDE.md`
"Testing protocol"). Run by a human against live Ollama; the agent prepared it
and stops. Card: `tasks/done/task-config-generation-profiles.md`.

What this verifies: after the config restructure, every kind of model request
Jarvis sends carries the same `think` value and the same Ollama options as
before, read from the new `[generation]` profiles; and a per-profile override
reaches only its own request kind.

Automated counterpart already green: `python -m pytest` (includes
`tests/test_generation_payloads.py`, which pins the options per request kind
for a config in your shape). This handoff checks the same thing end to end on
the running app.

## Literal references used throughout

- Launch: `python -m jarvis --status-console --debug` from the repository root
  (`--debug` requires `--status-console`, `src/jarvis/app.py` `parse_args`).
  Never run two instances at once.
- Clipboard submit hotkey: `[hotkeys].clipboard_submit`, default `ctrl+alt+v`
  (`src/jarvis/core/config.py` `HotkeySettings.clipboard_submit`; your
  `config.toml` sets the same value). It submits the current clipboard text as
  a question.
- Shutdown hotkey: `[hotkeys].shutdown`, default `ctrl+alt+q`
  (`HotkeySettings.shutdown`).
- Reasoning level and response mode are set by clicking the buttons on the
  Status tab (Thinking mode: Off / Low / Medium / High, in Russian UI
  Выкл / Низкий / Средний / Высокий; Response mode: Text / Voice / Text+voice,
  in Russian UI Текст / Голос / Текст+голос). Clicking a button selects that
  value directly, whatever the current state, so no starting state is assumed.
- Debug transcript: `<[logging].directory>/jarvis-debug.jsonl`; the directory
  defaults to `logs` (`LoggingSettings.directory`) and the file name is
  `TRANSCRIPT_FILE_NAME` in `src/jarvis/core/debug_transcript.py`. The checker
  in step 5 finds it for you.

## Step 1 - migrate config.toml (it no longer loads as-is)

1.1. Confirm the hard migration fires on your current file:

```
python -c "from jarvis.core.config import load_settings; load_settings()"
```

Expect exactly: `ConfigError: [backend].temperature (config.toml) moved to
[generation].temperature`.

1.2. Edit `config.toml`:

- In `[backend]`, delete these five lines: `temperature = 0.618`,
  `top_p = 0.9`, `top_k = 50`, `min_p = 0.05`, `repeat_penalty = 1.025`.
- In `[prompts]`, delete these four lines: `warmup = "Hello"`,
  `reasoning_low = "@prompts/think-level-1.md"`,
  `reasoning_medium = "@prompts/think-level-2.md"`,
  `reasoning_high = "@prompts/think-level-3.md"`.
- Immediately above the `[prompts]` header, insert:

```toml
[generation]
temperature = 0.618
top_p = 0.9
top_k = 50
min_p = 0.05
repeat_penalty = 1.025

[generation.dialog.low]
prompt = "@prompts/think-level-1.md"

[generation.dialog.medium]
prompt = "@prompts/think-level-2.md"

[generation.dialog.high]
prompt = "@prompts/think-level-3.md"

[generation.warmup]
prompt = "Hello"
```

1.3. Rerun the command from 1.1. Expect no output and no error.

Unrelated to this change, for your attention only: in `[prompts]` the comment
block "story-v1.9.0 task 4: opt-in voice intent probe ..." sits above
`voice_turn_instruction`, which is not the voice-intent probe. Leave or fix it
as you like; it has no effect.

## Step 2 - run the request kinds

2.1. Note the current local time as `YYYY-MM-DDTHH:MM:SS` (for example
`2026-09-26T21:05:00`). Call it SINCE.

2.2. Launch Jarvis (command above). Wait for the warm-up to finish (the
events panel shows the warm-up result). That was request kind `warmup`.

2.3. Status tab: click Thinking mode Off and Response mode Text. Copy
`Сколько будет 17 умножить на 23?` to the clipboard and press `ctrl+alt+v`.
Wait for the answer. Request kind: `dialog.off`.

2.4. Status tab: click Thinking mode Medium (Средний). Copy the same question
and press `ctrl+alt+v`. Wait for the answer. Request kind: `dialog.medium`.

2.5. Status tab: click Thinking mode Off and Response mode Text+voice. Copy
`Назови три планеты земной группы.` and press `ctrl+alt+v`. Wait until the
spoken commentary finishes. Request kinds: `dialog.off`, then
`spoken_derivative`.

2.6. Say one short question aloud into the microphone (anything, e.g.
"какая сегодня погода на Марсе") and wait for the answer. This creates a
voice event for step 2.8.

2.7. Journal tab, current session: open Annotations and click
"Generate for session" (Сгенерировать для сессии). Wait for the annotation.
Request kind: `annotation`.

2.8. Journal tab: on the voice event from 2.6, click "Transcribe"
(Расшифровать). Wait for the transcript. Request kind: `transcription`.

2.9. Press `ctrl+alt+q` to shut Jarvis down.

## Step 3 - read what was sent

```
python -m manual.manual_check_generation_profiles --since SINCE
```

Expect, in time order, one block per exchange. Each block prints `think=`,
the first message, and `options:`.

- Every block's `options` is exactly:
  `{"flash_attention": true, "kv_cache_type": "q8_0", "min_p": 0.05,
  "num_ctx": 65536, "repeat_penalty": 1.025, "temperature": 0.618,
  "top_k": 50, "top_p": 0.9}`.
- `think` per exchange: warm-up `False` (first message `user: Hello`);
  2.3 `False`; 2.4 `'medium'`; 2.5 first pass `False`, then the derivative
  `False` (first message starts `system: Тебе передан точный текст`); 2.6
  `False`; annotation `False`; transcription `False`.
- If your MCP module is enabled and a turn used a tool, that turn shows more
  than one exchange with the same `think` and `options`; that is the tool loop
  and is expected.

## Step 4 - a per-profile override reaches only its own request kind

4.1. Add to `config.toml`, below the `[generation.warmup]` table:

```toml
[generation.annotation]
temperature = 0.9
```

4.2. Note a new SINCE, launch Jarvis, repeat 2.3 and 2.7, shut down with
`ctrl+alt+q`, run the step-3 command with the new SINCE.

4.3. Expect: the annotation exchange shows `"temperature": 0.9`; the warm-up
and 2.3 exchanges still show `"temperature": 0.618`. All other options are
unchanged.

4.4. Remove the two lines added in 4.1 (or keep them, if you want warmer
annotations).

## What to report back

The step-3 and step-4 outputs, or the first step whose result differs from
the expectation, with the output.
