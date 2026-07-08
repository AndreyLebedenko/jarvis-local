# Story v1.2.8: Multilingual speech markup

**Status:** Backlog.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.8

## User-facing goal

Let Jarvis speak mixed Russian and English responses correctly by accepting a
small SSML-inspired markup contract from the LLM, parsing it into language
segments, and routing those segments through the TTS layer without speaking
control tags aloud.

The first implementation should be simple: preserve the current Silero runtime
path, add a robust parser and tests, and avoid choosing the long-term
multilingual TTS engine until the segment contract is proven. The markup should
stay close enough to SSML that a future TTS engine with native `<lang>` support
can adopt more of the standard without changing the LLM-facing contract.

## Context

Current Jarvis TTS is Russian-first. `tts.py` uses Silero `ru/v3_1_ru`, applies
Russian number normalization, and transliterates Latin text into Cyrillic as a
fallback because the current Silero model does not include Latin symbols.

Manual Gemma4 session tests on 2026-07-08 showed that the model can follow this
SSML-inspired language markup shape reliably enough for a first parser:

```xml
<speak>
  <lang xml:lang="ru">Русский текст.</lang>
  <lang xml:lang="en">English text.</lang>
</speak>
```

Silero supports a subset of SSML (`speak`, `break`, `prosody`, `p`, `s`) via
`ssml_text`, but does not support `lang`. Therefore `lang` is a Jarvis routing
tag, not a tag that should be passed through to Silero.

## Boundaries

- This story defines and parses Jarvis speech markup; it does not migrate to a
  new production TTS engine.
- The supported v1 markup subset is intentionally small:
  - optional `<speak>` wrapper;
  - `<lang xml:lang="ru">...</lang>`;
  - `<lang xml:lang="en">...</lang>`.
- Do not claim full SSML compatibility.
- Do not pass `<lang>` tags to any TTS engine.
- Do not implement automatic language detection as the primary source of truth.
- Do not implement "answer in the language of the request" as a product
  behavior in this story.
- Do not change conversation history retention for media.

## Acceptance Criteria

- [ ] A pure parser converts supported speech markup into ordered language
      segments.
- [ ] The parser accepts plain text and treats it as the default language
      (`ru`) for backward compatibility.
- [ ] The parser accepts an optional `<speak>` wrapper.
- [ ] The parser supports `xml:lang="ru"` and `xml:lang="en"`.
- [ ] The parser normalizes common region variants such as `ru-RU` to `ru` and
      `en-US` to `en`, or explicitly rejects them with a documented fallback.
- [ ] Adjacent segments with the same language are merged.
- [ ] Punctuation-only or very short connective segments do not produce
      standalone TTS calls when they can be safely attached to a neighboring
      segment.
- [ ] Broken markup uses a soft fallback: strip known control tags where safe
      and speak the remaining text as the default language, while logging a
      warning.
- [ ] Parser tests cover Russian-only, English-only, mixed Russian/English,
      adjacent same-language segments, punctuation smoothing, text outside
      tags, unsupported languages, malformed tags, and code-like identifiers.
- [ ] The TTS layer does not speak `<speak>`, `<lang>`, or `xml:lang` text.
- [ ] `python -m pytest` passes.

## Task Card Sequence

1. Speech markup parser.
   - Introduce a pure parser module.
   - Return a structured segment type with `language` and `text`.
   - Add parser tests before wiring it into playback.
   - See `tasks/story-v1.2.8-task-1-speech-markup-parser.md`.

2. TTS buffering integration.
   - Parse each completed speakable unit after the existing sentence boundary.
   - Preserve current sentence buffering behavior.
   - Ensure tags are never sent to Silero as spoken text.
   - See `tasks/story-v1.2.8-task-2-tts-buffering-integration.md`.

3. Prompt contract update.
   - Update Jarvis's system prompt so assistant responses use the markup
     contract.
   - Keep responses concise enough for low-latency speech.
   - Keep reasoning/thinking text out of `ResponseToken` consumers.
   - See `tasks/story-v1.2.8-task-3-system-prompt-speech-markup-contract.md`.

4. Manual markup handoff.
   - Provide fixed human-run prompts that check whether Gemma4 keeps the
     markup stable under mixed Russian/English, identifiers, quotes, and
     punctuation.
   - Record the verified behavior in `PROJECT.md`.
   - See `tasks/story-v1.2.8-task-4-manual-markup-handoff.md`.

## Open Questions

- Should display/history store raw tagged assistant text, clean text with tags
  removed, or a structured representation?
- Should unsupported languages fall back to `ru`, be skipped, or be routed to
  a future generic engine path?
- Should Silero-supported SSML tags such as `<break>` be preserved inside each
  language segment in the first implementation, or should v1 strip everything
  except text and language routing?
- Should punctuation smoothing attach punctuation to the previous segment, the
  next segment, or use a conservative language-default rule?

## Stop Conditions

- Stop if the parser requires a full XML/SSML implementation rather than the
  small subset above.
- Stop if malformed markup cannot be handled without risking spoken control
  tags.
- Stop if integrating parsed segments forces a large rewrite of sentence
  buffering or playback orchestration.
- Stop if the markup contract creates a conflict between TTS output, visible
  UI text, and conversation history.
