# Task v2.1.1-4: Voice mode

Status: Completed.

Story: `tasks/done/story-v2.1.1-proxy-speech-modes.md`, task 4 (Size: M).

## Problem

In Voice mode the proxy still sends the default system prompt and speaks every restored
sentence verbatim, so Markdown, abbreviations and Roman numerals are read badly. The owner's
live run of 2026-10-27 (task 3 build, where every mode was still Text) also showed that
abbreviations such as "тыс.", "°C" and "г." are read as written; the story's cleanup module
covered Markdown and Roman numerals only. The owner approved extending the cleanup with
abbreviations (2026-10-27).

## Design

1. `VOICE_SYSTEM_PROMPT` (`common/payload.py`) is `DEFAULT_SYSTEM_PROMPT` plus one fixed
   paragraph on the same paragraph (no blank line, so `sent_view` can split the record). No user
   data, no digit runs, no address-like words, no `speech_language_*` directive.
   `system_prompt_for(mode)` picks it for `voice` and the default prompt otherwise.
2. The request pipeline builds the payload with the prompt of the latched mode.
3. `sent_view` knows both prompts (`has_default_system_prompt`, `split_known_system_prompt`);
   the Status Console feed returns the matching prompt as `system_text`.
4. `answer/speech_preparation.py`: `speech_preparation_of(mode)` is `strip_speech_control_tags`
   then `clean_for_speech` in Voice and the identity otherwise. `AnswerPresenter.present` takes
   it as a parameter; the shown text is never touched.
5. `clean_for_speech` expands abbreviations: `тыс.`, `млн`, `млрд`, `трлн` after a number;
   `°C` (with or without a number); `г.`/`гг.` after a year; `т.е.`, `т.д.`, `т.п.`. The count
   form follows the number. An abbreviation dot that closes a sentence is kept.
6. `PROJECT.md` describes the mode behavior.

## Boundary

Text and Text+Voice behave as before (Text+Voice is task 5). No change to sanitize, check, the
gate rules, restoration, the external client, config keys, the Silero adapter, the UI scripts.
README is task 6.

## Acceptance criteria

- [x] Voice sends `VOICE_SYSTEM_PROMPT`; Text sends the byte-identical default prompt.
- [x] The gate allows the voice prompt; the sent view folds it like the default prompt.
- [x] Voice speaks the cleaned sentence and shows it as received; Text speaks as received.
- [x] Abbreviation tests; `python -m pytest`, `ruff check`, `ruff format --check` green.

## Outcome (2026-10-27)

Implemented as designed. Full suite green except the known timezone failure of
`tests/test_journal.py::test_new_session_id_uses_sortable_local_timestamp_prefix`.
Findings and limits:
- The sentence splitter splits after "тыс." followed by a space, so "450 тыс. человек" reaches
  the speaker as two sentences ("450 тыс." and "человек."). The count form still comes from the
  number; the pause between them is a splitter property, not changed here.
- "2002 г." becomes "2002 года" (not "2002-го года"): the Silero adapter reads digits as
  cardinals, so a hyphenated ordinal suffix would be read wrongly, and the case of the year
  is not inferred. Other abbreviations (km, kg, "др.", "см.") are left alone.
- The voice contract is a request to the model; the cleanup is the only guarantee.
- The live check (hotkey to Voice, a real answer with Markdown, "XX век", "тыс.", "°C") is human-run.
