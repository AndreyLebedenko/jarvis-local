# TTS Engines Spike Results 1.0

Status: completed (closed 2026-07-11)

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
- Human follow-up after the initial spike: Piper installation succeeded with a
  single command, `python -m pip install piper-tts`. Subjective English speech
  quality sounded better than the current Silero Russian baseline, and
  perceived latency sounded lower than Silero. This was not a matched
  same-language benchmark: the comparison was English Piper output against
  Russian Silero output, so treat it as a promising usability signal rather
  than a final engine-quality conclusion.
- Kokoro was not conclusively evaluated in this environment.
  The local Python stack hit an import-time `torch` / `torchvision`
  compatibility error. Resolving its installation and startup problems made
  the research cost unacceptable, so Kokoro is unsuitable for the current
  project boundary; this is not a model-quality conclusion.
- XTTS-v2 is documented as multilingual, but its installation and startup
  complexity likewise made further investigation unacceptably expensive.
  It is unsuitable for the current project boundary; this is not a negative
  model-quality measurement.

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
- Human follow-up compared f16 and q8_0 across Gemma4 and gpt-oss at large
  contexts. Any accuracy loss was not detectable on the owner's tasks, while
  q8_0 improved speed by 10-20%. q8_0 is the preferred large-context profile.

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
- Production is confirmed for the tested Silero/Russian plus Piper/English
  configuration. The routing architecture does not bind either engine to a
  language; Silero or Piper may be configured for either supported language
  with a compatible model. Kokoro and XTTS-v2 remain out of scope unless
  their integration cost changes materially.

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

## Closed follow-up

- v1.2.9 validated the Silero/Russian plus Piper/English production
  configuration without making it a required language-to-engine mapping.
- v1.2.8 replaced language tags with deterministic charset segmentation.
- Final cache and candidate-engine decisions are recorded in `PROJECT.md`.

## Sources

- Silero model manifest: [snakers4/silero-models models.yml](https://github.com/snakers4/silero-models/blob/master/models.yml)
- XTTS-v2 docs: [coqui-ai/TTS XTTS model page](https://github.com/coqui-ai/TTS/blob/dev/docs/source/models/xtts.md)
- XTTS-v2 model card: [coqui/XTTS-v2](https://huggingface.co/coqui/XTTS-v2)
