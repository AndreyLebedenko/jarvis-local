# Task: TTS buffering integration

**Story:** `tasks/story-v1.2.8-multilingual-speech-markup.md`
**Status:** Backlog.
**Release:** v1.2.8
**Depends on:** `tasks/story-v1.2.8-task-1-speech-markup-parser.md`

## Summary

Wire parsed speech-markup segments into the existing TTS buffering path so
Jarvis never speaks markup tags and can prepare for language-aware synthesis
without changing the production TTS engine yet.

## Current Boundary

- Integrate parser output after the existing sentence/speakable-unit boundary.
- Preserve current playback orchestration and sentence buffering behavior.
- Preserve current Silero runtime behavior by default.
- Do not migrate to Silero multilingual, XTTS-v2, or any other production TTS
  engine in this task.
- Do not add automatic language detection.

## Acceptance Criteria

- [ ] `TtsOutput` or its immediate helper path parses completed speakable units
      before synthesis.
- [ ] `<speak>`, `<lang>`, and `xml:lang` are never sent as spoken text.
- [ ] Existing unmarked assistant text still speaks through the current Silero
      path.
- [ ] Existing sentence buffering tests remain meaningful.
- [ ] Tests prove that marked Russian-only text speaks as clean Russian text.
- [ ] Tests prove that marked mixed Russian/English text is decomposed into
      ordered segments without spoken control tags.
- [ ] The current Silero path either handles non-Russian segments through the
      existing transliteration fallback or explicitly records that true English
      synthesis waits for a later engine-routing task.
- [ ] Punctuation and short connective spans do not trigger unnatural
      standalone synthesis calls.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Do not run speaker/audio hardware tests as the agent.

## Stop Conditions

- Stop if integration requires a large rewrite of sentence buffering or
  playback orchestration.
- Stop if parser output creates an unresolved conflict with current Silero
  normalization or transliteration.
- Stop if testing this path requires real audio hardware rather than pure
  fakes.
