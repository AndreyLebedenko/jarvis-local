# Story v1.2.8: Multilingual speech markup

**Status:** Completed.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.8

## User-facing goal

Let Jarvis speak mixed Russian and English responses correctly by routing
plain model text into language segments before TTS.

The successful implementation preserves the current Silero runtime path and
avoids choosing the long-term multilingual TTS engine. The attempted
LLM-authored SSML-like markup contract was rejected after manual testing showed
Gemma4 could not keep it stable; runtime routing now uses deterministic
Russian/English charset segmentation instead.

## Context

Current Jarvis TTS is Russian-first. `tts.py` uses Silero `ru/v3_1_ru`, applies
Russian number normalization, and transliterates Latin text into Cyrillic as a
fallback because the current Silero model does not include Latin symbols.

Manual Gemma4 session tests on 2026-07-08 initially suggested that the model
could follow this SSML-inspired language markup shape:

```xml
<speak>
  <lang xml:lang="ru">Русский текст.</lang>
  <lang xml:lang="en">English text.</lang>
</speak>
```

Silero supports a subset of SSML (`speak`, `break`, `prosody`, `p`, `s`) via
`ssml_text`, but does not support `lang`. Therefore `lang` was tested as a
Jarvis routing tag, not a tag to pass through to Silero. Later task-4 manual
checks rejected that path in favor of charset routing.

## Boundaries

- This story defines and tests Jarvis language routing; it does not migrate to
  a new production TTS engine.
- The runtime-supported v1 language routing contract is intentionally small:
  - plain model text;
  - Cyrillic routes to `ru`;
  - Latin routes to `en`;
  - neutral digits, whitespace, and punctuation attach to neighboring text.
- Do not claim full SSML compatibility.
- Do not pass `<lang>` tags to any TTS engine.
- Do not implement automatic language detection as the primary source of truth.
- Do not implement "answer in the language of the request" as a product
  behavior in this story.
- Do not change conversation history retention for media.

## Acceptance Criteria

- [x] A pure parser converts supported speech markup into ordered language
      segments.
- [x] The parser accepts plain text and treats it as the default language
      (`ru`) for backward compatibility.
- [x] The parser accepts an optional `<speak>` wrapper.
- [x] The parser supports `xml:lang="ru"` and `xml:lang="en"`.
- [x] The parser normalizes common region variants such as `ru-RU` to `ru` and
      `en-US` to `en`, or explicitly rejects them with a documented fallback.
- [x] Adjacent segments with the same language are merged.
- [x] Punctuation-only or very short connective segments do not produce
      standalone TTS calls when they can be safely attached to a neighboring
      segment.
- [x] Broken markup uses a soft fallback: strip known control tags where safe
      and speak the remaining text as the default language, while logging a
      warning.
- [x] Parser tests cover Russian-only, English-only, mixed Russian/English,
      adjacent same-language segments, punctuation smoothing, text outside
      tags, unsupported languages, malformed tags, and code-like identifiers.
- [x] The TTS layer no longer depends on model-authored tags; runtime routing
      uses charset segmentation over plain text.
- [x] `python -m pytest` passes.

## Task Card Sequence

1. Speech markup parser.
   - Introduce a pure parser module.
   - Return a structured segment type with `language` and `text`.
   - Add parser tests before wiring it into playback.
   - See `tasks/done/story-v1.2.8-task-1-speech-markup-parser.md`.

2. TTS buffering integration.
   - Parse markup BEFORE sentence buffering (decision recorded in the task
     card, 2026-07-09): stream tokens through the incremental scanner, then
     sentence-buffer within language segments; a closing `</lang>` is an
     additional flush boundary.
   - Preserve current sentence buffering behavior for unmarked text.
   - Ensure tags are never sent to Silero as spoken text.
   - See `tasks/done/story-v1.2.8-task-2-tts-buffering-integration.md`.

3. Prompt contract update.
   - Update Jarvis's system prompt so assistant responses use the successful
     plain-text language-routing contract.
   - Keep responses concise enough for low-latency speech.
   - Keep reasoning/thinking text out of `ResponseToken` consumers.
   - See `tasks/done/story-v1.2.8-task-3-system-prompt-language-routing-contract.md`.

4. Manual language-routing handoff.
   - Provide fixed human-run prompts that check whether Gemma4 emits plain text
     and whether charset segmentation routes mixed Russian/English,
     identifiers, quotes, and punctuation correctly.
   - Record the verified behavior in `PROJECT.md`.
   - See `tasks/done/story-v1.2.8-task-4-manual-language-routing-handoff.md`.

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
