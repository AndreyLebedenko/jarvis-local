# Task 1: Emphasis normalizer and stripper

**Status:** Completed.
**Story:** `tasks/story-silero-v5-emphasis-markers.md` (approved 2026-11-25).

## Summary

A pure module that decides which asterisk markers in one speech unit are kept
for Silero v5 and which are removed, plus a stripper that removes all of them.
No I/O, no wiring, no config.

## Boundary

New files only:
- `src/jarvis/audio/speech_emphasis.py`
- `tests/test_speech_emphasis.py`

Must NOT touch: `tts_silero.py`, `tts.py`, `voice_guide.py`, `config.py`,
`personal_proxy/answer/speech_cleanup.py`, the spike script.
Later cards do the wiring.

## Interface

- `normalize_emphasis(unit: str) -> str`: returns the unit with only the
  allowed markers kept; every other asterisk removed.
- `strip_emphasis(unit: str) -> str`: returns the unit with every `*` removed.

The input is one speech unit, one sentence as produced by `SpeechUnitBuffer`,
never a whole paragraph. The module does no sentence splitting.

## Rules

1. A marker is `*word*` where `word` is a run of non-space, non-asterisk
   characters containing at least one letter or digit (owner, 2026-11-25, after
   review: a lone dash or `?` must not become an intonation centre), and the
   opening asterisk is not preceded, and the closing one is not followed, by a
   word character or another asterisk. So `**bold**`, `*two words*`, `a*b*c`,
   and `*-*` are not markers.
2. The unit is a question when its last sentence punctuation run contains `?`
   (for example `?`, `?!`, `?..`), optionally followed by closing quotes or
   brackets. Otherwise it is a statement.
3. Question: keep at most two markers. With three or more, keep the first and
   the last.
4. Statement: keep at most one marker, the first.
5. Every marker that is not kept becomes its plain word. Every other `*`
   (unpaired, doubled, around several words) is removed. Spaces are not
   collapsed or added by the module.
6. A unit with no asterisk is returned unchanged.

Defaults for rules 3 and 4 beyond the spike evidence (two markers in a question,
one in a statement) are chosen here, not heard: "first and last" and "first".
Task 5 checks them by ear.

## Tests (each name states the invariant)

- one marker in a question stays; one marker in a statement stays;
- two markers in a question stay; two markers in a statement leave only the
  first;
- three markers in a question leave the first and the last;
- `**bold**`, `*two words*`, an unpaired `*`, and `a*b*c` leave no asterisk and
  the words intact;
- `?!` and a closing quote after `?` still count as a question;
- a unit without asterisks is returned identical;
- `strip_emphasis` removes every asterisk, markers included, and keeps the
  words;
- Russian text with `ё`, hyphenated words, and digits survives.

## Acceptance criteria

- `python -m pytest`, `ruff check .`, and `ruff format --check .` pass.
- The module imports nothing from `jarvis` and no I/O library.
- No other file is changed.
