# Task 2: Silero capability and engine boundary

**Status:** Completed.
**Story:** `tasks/story-silero-v5-emphasis-markers.md` (decision A: opt-in,
default off).
**Predecessor:** `tasks/done/task-silero-emphasis-1-normalizer.md`.

## Summary

The engines decide what happens to `*` in the unit they are given. Silero keeps
the normalized markers only when its route opts in. Every other case removes
every asterisk. Where the text comes from is task 3; the engine only enforces
its own side.

## Why the engine strips even when the feature is off

`v5_6_ru` is already a supported route. Markdown asterisks in canvas that is
read verbatim reach it today, and a v5 model may turn them into intonation. A
stripper at the boundary closes that, so with the feature off no asterisk ever
reaches a model.

## Boundary

Files to change:
- `src/jarvis/core/config.py`: `SileroTtsSettings.emphasis: bool = False`. The
  schema projection, TOML parsing, and transport parsing are generic over the
  dataclass fields; nothing else in `config.py` changes.
- `src/jarvis/audio/tts_silero.py`: the emphasis step in
  `SileroEngine.synthesize`.
- `src/jarvis/audio/tts_piper.py`: strip in `PiperEngine.synthesize`.
- `config.example.toml`: the new key, commented, next to `put_accent`.
- `src/jarvis/ui/status_console_ui/strings.js` (en and ru label
  `config_tts_field_emphasis`) and `demo.js` (the demo schema and route), because
  the Settings tab renders every schema field and needs a label for each.
- Existing tests that list the Silero route fields or values, and new tests.

Must NOT touch: `voice_guide.py`, `app.py`, the personal proxy, `speech_cleanup.py`,
`tts.py` buffering, the MCP tool description. That is tasks 3 and 4.

## Design

1. **Order in `SileroEngine.synthesize`.** The emphasis step runs after number
   and Latin conversion and before the model call. Reason: `*21*` becomes
   `*двадцать один*`, which the normalizer then drops as a multi-word marker
   instead of sending a garbled one, while `*API*` becomes `*апи*` and
   `*3*` becomes `*три*`, which stay valid.
2. **Opt-in.** `route.emphasis` true: `normalize_emphasis(prepared)`. False:
   `strip_emphasis(prepared)`. The step applies for every Silero model language,
   not only `ru`.
3. **No model-name validation.** `emphasis = true` on a model that does not
   understand the markers is not a config error, the same convention as
   `put_accent`: an unsupported combination shows up on first use. The example
   config says the markers are for the v5 Russian models. The owner confirmed
   2026-11-25 that no stricter validation is wanted for now.
4. **Piper** always strips.

## Tests

- engine with `emphasis = False` sends no `*` to the model for `*слово*`, `**слово**`
  and a stray `*`;
- engine with `emphasis = True` sends a question's two markers and a statement's
  one marker, and drops the rest;
- number and Latin conversion happen before normalization (`*3*` arrives as
  `*три*`, `*21*` arrives as plain `двадцать один`, `*API*` arrives as `*апи*`);
- English-language Silero route strips when off and normalizes when on;
- Piper receives text without any `*`;
- the route field list, the default values, the TOML parse of `emphasis = true`,
  a non-boolean value being rejected, and the transport payload carry the new
  field.

## Acceptance criteria

- `python -m pytest`, `ruff check .`, and `ruff format --check .` pass.
- A config without the key behaves as before for text without asterisks.
- No file outside the boundary list is changed.
