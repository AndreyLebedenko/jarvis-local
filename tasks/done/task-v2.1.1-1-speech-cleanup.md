# Task v2.1.1-1: Speech cleanup module

Status: Completed.

Story: `tasks/story-v2.1.1-proxy-speech-modes.md`, task 1 (Size: S-M).

## Problem

The external answer is spoken verbatim. Markdown markers and Roman numerals are read badly
("asterisk asterisk", "Roman twenty").

## Design

1. One pure module, `src/jarvis/personal_proxy/answer/speech_cleanup.py`, with one public
   function `clean_for_speech(text: str) -> str`. No I/O, no settings, no wiring (wiring is
   task 4 and task 5).
2. Markdown, removed or reduced to the words they carry: emphasis markers (`**`, `__`, `*`,
   `_` around a word or phrase), heading markers at line start, list markers at line start
   (`-`, `*`, `+`, `1.`, `1)`), block quote markers, inline code backticks (the code text
   is kept), links `[text](url)` become `text`. A marker that is part of a word or an
   expression is kept: `snake_case`, `2*3`, `a_b`, a lone `*`. Bare URLs are out of scope.
3. Roman numerals, Russian century words only: a numeral I..XXX followed by a form of
   "век" (`век`, `века`, `веку`, `веком`, `веке`, `веков`, `векам`, `веками`, `веках`) becomes
   the ordinal in the case of that word: `XX век` -> `двадцатый век`, `в XX веке` ->
   `в двадцатом веке`, `XXI века` -> `двадцать первого века`. Plural forms use the plural
   ordinal (`XIX-XX веках` is out of scope). A numeral anywhere else, and any ambiguous token
   (`I`, `V`, `X`, `MIX`, `CD`), is left unchanged. Lowercase Latin letters are never a
   numeral. Invalid numerals (`IIII`, `VX`) are left unchanged.
4. The function is idempotent and keeps everything it does not recognise byte for byte.
   Whitespace runs created by removals are collapsed on the touched line only.

## Boundary

New module and its test file `tests/test_personal_proxy_speech_cleanup.py` only. No change
to `answer_voice.py`, the presenter, TTS, the sanitize pass, the gate, config, or docs
(`PROJECT.md` is updated in task 6 with the wiring). No dependency added.

## Acceptance criteria

- [x] Tests, one self-explanatory case each: every Markdown form in design item 2 and its
      kept-as-is counterpart; every century word form with its case; `XX`, `XXI`, `XIV`;
      ambiguous tokens and invalid numerals unchanged; idempotence; plain text unchanged
      byte for byte; Russian and English plain text unchanged; multi-line input.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` are green.

## Outcome (2026-10-27)

141 tests in `tests/test_personal_proxy_speech_cleanup.py`; `ruff check` and `ruff format --check`
green; full suite green except the known timezone failure of
`tests/test_journal.py::test_new_session_id_uses_sortable_local_timestamp_prefix`.
Resolved ambiguity: a single `I`, `V`, `X` is converted only when a form of "vek" follows
directly (`X vek` -> ordinal); standalone they stay unchanged. Plural cases use plural
ordinals. Numerals above XXX, hyphen-preceded numerals, and monarch names are unchanged.
