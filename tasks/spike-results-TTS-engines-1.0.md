# TTS Engines Spike Results 1.0

Status: промежуточный итог

Scope: local TTS engine research for Jarvis v1.2.5, focused on Silero,
Piper, Kokoro, and XTTS-v2 behavior, installability, and multilingual
potential.

## Verified facts

- Current Jarvis runtime still uses Silero in a Russian-only setup.
  `tts.py` loads `silero_tts(language="ru", speaker="v3_1_ru")`, and
  `setup_tts_model.py` downloads the same model path.
- The current Silero output path is not multilingual by itself.
  Jarvis's `tts.py` applies Russian number normalization and a
  best-effort Latin-to-Cyrillic transliteration before synthesis, which
  makes the existing pipeline effectively Russian-first.
- Silero does have a multilingual package in the published model list:
  `multi/v2_multi.pt`.
  The official manifest includes speakers tagged with at least `ru` and
  `en`, which means Silero can support multiple languages through model
  and speaker selection, not through one language-agnostic voice.
- That Silero multilingual support is not the same thing as seamless
  mixed-language speech.
  The model selection is still per language/speaker, so free code-switching
  needs explicit routing in the application layer.
- Piper is usable as a local engine, but the checked voice was
  monolingual English.
  The English voice works for English input; it does not make Russian
  support automatic.
- Kokoro was not conclusively evaluated in this environment.
  The local Python stack hit an import-time `torch` / `torchvision`
  compatibility error, so there was no reliable model-level conclusion
  from this session.
- XTTS-v2 remains the strongest documented path for native English and
  Russian support in one local model.
  It is explicitly multilingual in the Coqui documentation and is the
  better fit if the goal is natural mixed-language output rather than
  language-specific voice routing.

## Measured run

- Manual run on 2026-07-08 used `backend.flash_attention = true` and
  `backend.kv_cache_type = q8_0`.
- Backend metrics reported:
  - wall_seconds: 3.68
  - load_seconds: 3.47
  - prompt_eval_seconds: 0.12
  - eval_seconds: 0.08
  - eval_count: 6
- Silero metrics reported:
  - speaker: `baya`
  - load_seconds: 0.52
  - peak_vram_delta_mib: 0
- Prompt timings reported for Silero:
  - `russian`: first_audio_seconds 1.24, total_seconds 4.50
  - `english`: first_audio_seconds 0.99, total_seconds 4.87
  - `mixed_latin`: first_audio_seconds 0.37, total_seconds 4.67
  - `numbers`: first_audio_seconds 0.32, total_seconds 5.98
  - `short_answer`: first_audio_seconds 0.24, total_seconds 2.75
  - `code_like`: first_audio_seconds 0.39, total_seconds 4.39
- Only the q8_0 profile is verified so far; f16 comparison remains open.

## Conclusions

- Yes, Silero can be part of a multilingual Jarvis setup, but only if we
  switch away from the current `v3_1_ru` path and add language-aware
  routing in the app.
- For a controlled bilingual setup, the LLM should emit explicit language
  markers or another structured signal that the TTS layer can parse.
  The TTS layer then needs to:
  - strip the markers;
  - split text into language-homogeneous segments;
  - choose the right Silero language/speaker for each segment.
- The current `tts.py` behavior would need to change in three places if
  Silero multilingual support is adopted:
  - model loading;
  - language-specific text preprocessing;
  - sentence/segment dispatch.
- If the goal is freer English/Russian code-switching inside the same
  response, XTTS-v2 remains the cleaner long-term candidate.

## Practical implications for the LLM response format

- The LLM should not return raw mixed-language prose and expect TTS to
  infer everything reliably.
- A structured format is safer, for example:

```text
[lang=ru]Сейчас отвечу по-русски.[/lang]
[lang=en]Here is the English part.[/lang]
```

- The TTS layer should treat those tags as control data, not as spoken
  text.
- If we stay with Silero, Russian-only preprocessing should remain
  confined to Russian segments.
  English segments should not go through Russian number spelling or
  Latin transliteration.

## Files touched during the research

- `tts.py`
- `setup_tts_model.py`
- `manual_check_tts_engines.py`
- `manual_check_piper.py`
- `latest_silero_models.yml`
- `PROJECT.md`

## Open follow-up

- Verify whether a single Silero multilingual voice is sufficient for the
  desired UX, or whether mixed-language responses should move to XTTS-v2.
- If Silero stays in the stack, define a concrete response contract for
  language tags before changing runtime code.
- Record any final architectural choice in `PROJECT.md` when that choice
  is made.

## Sources

- Silero model manifest: [snakers4/silero-models models.yml](https://github.com/snakers4/silero-models/blob/master/models.yml)
- XTTS-v2 docs: [coqui-ai/TTS XTTS model page](https://github.com/coqui-ai/TTS/blob/dev/docs/source/models/xtts.md)
- XTTS-v2 model card: [coqui/XTTS-v2](https://huggingface.co/coqui/XTTS-v2)
