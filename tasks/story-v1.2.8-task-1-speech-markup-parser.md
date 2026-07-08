# Task: Speech markup parser

**Story:** `tasks/story-v1.2.8-multilingual-speech-markup.md`
**Status:** Backlog.
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

- [ ] A structured segment type exists with `language` and `text`.
- [ ] Plain text parses as one default-language segment (`ru`).
- [ ] Optional `<speak>` wrapper is accepted.
- [ ] `<lang xml:lang="ru">...</lang>` creates Russian segments.
- [ ] `<lang xml:lang="en">...</lang>` creates English segments.
- [ ] Common region variants such as `ru-RU`, `ru_RU`, `en-US`, and `en_US`
      either normalize to `ru`/`en` or take a documented fallback path.
- [ ] Text outside `<lang>` is preserved as default-language text.
- [ ] Adjacent same-language segments are merged.
- [ ] Punctuation-only segments are not emitted as standalone segments when
      they can be safely attached to a neighboring segment.
- [ ] Unsupported language tags use a documented soft fallback.
- [ ] Malformed markup cannot result in spoken `<speak>`, `<lang>`, or
      `xml:lang` control text.
- [ ] Parser tests cover Russian-only, English-only, mixed language,
      identifiers, punctuation, adjacent same-language segments, unsupported
      language tags, text outside tags, and malformed markup.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if the parser requires a full XML/SSML implementation to satisfy this
  subset.
- Stop if malformed markup cannot be handled without risking spoken control
  tags.
- Stop if choosing the fallback behavior has non-obvious product consequences.
