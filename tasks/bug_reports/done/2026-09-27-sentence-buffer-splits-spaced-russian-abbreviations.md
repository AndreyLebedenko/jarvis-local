# SentenceBuffer splits spaced Russian abbreviations mid-abbreviation

**Detected at:** f9a4764 (main), while writing the grader for
`tasks/done/spike-single-pass-tts-block.md`, which reuses the production splitter.

**Status:** Closed 2026-09-27 on branch `fix/sentence-buffer-spaced-abbreviations`;
see "Resolution".

## Symptoms

`jarvis.audio.tts.SentenceBuffer` cuts a spaced two-letter abbreviation into
separate TTS utterances:

    "Это так, т. е. нужно помнить. " -> ["Это так, т.", "е.", "нужно помнить."]
    "Как в т. ч. и тут. "            -> ["Как в т.", "ч.", "и тут."]

The unspaced form is handled: `"т.е. нужно помнить. "` stays one sentence.
Standard Russian typography writes these abbreviations with a (often
non-breaking) space, so model output hits the broken form. The listener hears
"т" and "е" as two clipped utterances with pauses between them.

## Suspected cause

`_ABBREVIATIONS` (`src/jarvis/audio/tts.py`) holds `"т.е"`, `"т.д"`, `"т.п"`
as single tokens, and `_is_abbreviation` looks only at the last
whitespace-delimited word before the period. For `"т. е."` that word is `"т"`
and then `"е"`, neither of which is in the set. `"т.ч"` and `"т.к"` are
missing entirely. The module comment states the intended bias - a false
boundary "would cut off mid-abbreviation and produce broken speech, which is
the worse failure mode" - so this is a gap, not a design choice.

## Temporary decision

Not fixed in the spike: the spike card forbids any change under `src/jarvis`,
and the grader must measure time to first spoken sentence exactly as
production splits, defect included. Fixing it inside the grader alone would
make the spike's timing disagree with what TTS actually does. The grader's
tests use unspaced abbreviations, so they do not depend on this behavior.

## Future considerations

- Recognize a single Cyrillic letter followed by a period when the next word
  is also a single letter plus period (`т. е.`, `т. д.`, `т. п.`, `т. ч.`,
  `т. к.`), including a non-breaking space (U+00A0) between them.
- Add `т.ч` and `т.к` to the unspaced set.
- The splitter is shared by every mode that speaks, so the fix needs a
  regression test in `tests/` for both spaced and unspaced forms.

## Resolution (2026-09-27)

Fixed in `SentenceBuffer` (`src/jarvis/audio/tts.py`) with a rule instead of
the lookahead proposed above:

- A single "." right after a one-letter alphabetic word, in any script, is
  never a sentence boundary. This needs no lookahead: the word before the
  period has fully arrived by the time the boundary is checked, so streaming
  and chunking cannot change the result (tested char by char). It covers
  "т. е.", "т. д.", "т. п.", "т. ч." and "т. к.", a non-breaking space
  between the parts, and initials such as "А. С. Пушкин" and
  "J. R. R. Tolkien", which also used to split.
- The one-letter pronouns "я" and "I" are excluded. They end sentences far
  more often than they abbreviate anything, so "Это я. Потом ушёл." still
  splits after "я.".
- "!", "?" and runs such as "..." after a single letter still end a sentence.
- Leading opening punctuation is stripped before the check, so "(т. е.",
  «А. Б. Иванов» and "(т.е." no longer split behind a bracket or quote. This
  gap applied to the old abbreviation set too.
- "т.к" and "т.ч" were added to the unspaced abbreviation set.

The accepted cost follows the module's documented under-splitting bias:
"Вариант Б. Далее" and "и т. д. Потом" become one utterance, and such a
sentence at the very end of an answer is spoken at `flush()`. That delays
speech slightly but never breaks it. Regression tests are in
`tests/test_tts.py` next to the other `SentenceBuffer` tests.

Still out of scope, as before this fix: "1." at the start of a numbered line
is spoken as its own unit, and unspaced initials "А.Б." still split after
"А.Б.".
