# SentenceBuffer splits spaced Russian abbreviations mid-abbreviation

**Detected at:** f9a4764 (main), while writing the grader for
`tasks/spike-single-pass-tts-block.md`, which reuses the production splitter.

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
