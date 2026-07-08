# Task: Speech markup parser

**Story:** `tasks/story-v1.2.8-multilingual-speech-markup.md`
**Status:** Completed.
**Release:** v1.2.8

## Summary

Introduce a pure parser for Jarvis speech markup: a small SSML-like subset that
uses `<lang xml:lang="ru">` and `<lang xml:lang="en">` as Jarvis routing
metadata.

## Current Boundary

- Parser module and pure unit tests only.
- No TTS playback wiring in this task.
- No system prompt changes in this task.
- Do not claim full SSML support.
- Do not pass parser output to Silero yet.

## Acceptance Criteria

- [x] A structured segment type exists with `language` and `text`.
- [x] Plain text parses as one default-language segment (`ru`).
- [x] Optional `<speak>` wrapper is accepted.
- [x] `<lang xml:lang="ru">...</lang>` creates Russian segments.
- [x] `<lang xml:lang="en">...</lang>` creates English segments.
- [x] Common region variants such as `ru-RU`, `ru_RU`, `en-US`, and `en_US`
      either normalize to `ru`/`en` or take a documented fallback path.
- [x] Text outside `<lang>` is preserved as default-language text.
- [x] Adjacent same-language segments are merged.
- [x] Punctuation-only segments are not emitted as standalone segments when
      they can be safely attached to a neighboring segment.
- [x] Unsupported language tags use a documented soft fallback.
- [x] Malformed markup cannot result in spoken `<speak>`, `<lang>`, or
      `xml:lang` control text.
- [x] Parser tests cover Russian-only, English-only, mixed language,
      identifiers, punctuation, adjacent same-language segments, unsupported
      language tags, text outside tags, and malformed markup.
- [x] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if the parser requires a full XML/SSML implementation to satisfy this
  subset.
- Stop if malformed markup cannot be handled without risking spoken control
  tags.
- Stop if choosing the fallback behavior has non-obvious product consequences.
