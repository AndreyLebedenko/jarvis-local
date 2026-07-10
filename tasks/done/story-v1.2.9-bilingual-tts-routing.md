# Story v1.2.9: Bilingual TTS routing

**Status:** Completed.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.9

## User-facing goal

Let Jarvis pronounce mixed Russian and English responses with language-specific
TTS engines, using the existing charset language segmentation and a small
configuration shape for exactly two supported languages:

```toml
[tts.languages.ru]
engine = "silero"
model = "v3_1_ru"

[tts.languages.en]
engine = "piper"
model = ".local-models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
```

The first production target is the spike-winning route:

```text
ru -> Silero
en -> Piper
```

## Context

v1.2.8 already routes streamed model text into `ru` and `en` segments by
charset before sentence buffering. `TtsEngine.synthesize(text, language=...)`
already receives a language hint, but the default `SileroEngine` ignores it and
transliterates Latin fallback text for the Russian Silero model.

The v1.2.9 spike `tasks/spike-v1.2.9-bilingual-tts-routing.md` compared:

1. `ru`, `en` -> Silero.
2. `ru` -> Silero, `en` -> Piper.
3. `ru`, `en` -> Piper.

Human listening selected `silero_ru_piper_en` as the best route. Therefore the
implementation should preserve Silero for Russian and add Piper for English,
with configuration general enough to describe both languages explicitly.

## Boundaries

- Support only `ru` and `en` in this story.
- Keep charset segmentation as the only production language source.
- Keep ordered playback semantics: faster synthesis for a later segment must
  never play before an earlier segment.
- Do not implement automatic model downloads in Jarvis runtime.
- Do not add runtime network access beyond the existing local Ollama endpoint.
- Do not migrate Russian speech to Piper in this story.
- Do not add a UI for editing per-language TTS settings.
- Do not make `graphify-out/` or downloaded local model files part of git.

## Acceptance Criteria

- [x] Config can express per-language TTS routes for `ru` and `en`.
- [x] Default config preserves current behavior unless an English Piper model
      is explicitly configured.
- [x] Config validation rejects unsupported languages and unsupported engine
      names with clear errors.
- [x] Piper synthesis is behind the existing `TtsEngine` boundary, not mixed
      into sentence buffering or playback code.
- [x] A bilingual engine routes `ru` segments to Silero and `en` segments to
      Piper according to config.
- [x] `TtsOutput` still owns buffering and ordered playback; it does not know
      Piper-specific details.
- [x] English Piper model/config paths are validated before first response
      playback, failing clearly during app startup or TTS initialization.
- [x] Existing Silero-only behavior remains test-covered.
- [x] Pure automated tests pass with `python -m pytest`.
- [x] Human-run manual TTS check confirms mixed Russian/English responses use
      the configured engines and remain ordered.
- [x] `PROJECT.md` records the verified production route and manual result.

## Task Card Sequence

1. Config shape for per-language TTS routes.
   - See `tasks/story-v1.2.9-task-1-tts-language-config.md`.

2. Piper engine adapter.
   - See `tasks/story-v1.2.9-task-2-piper-engine-adapter.md`.

3. Bilingual TTS router integration.
   - See `tasks/story-v1.2.9-task-3-bilingual-tts-router.md`.

4. Manual handoff and project record.
   - See `tasks/story-v1.2.9-task-4-manual-bilingual-tts-handoff.md`.

## Stop Conditions

- Stop if Piper cannot be isolated behind `TtsEngine` without changing
  buffering/playback responsibilities.
- Stop if Piper path validation would require runtime network access.
- Stop if the config shape conflicts with existing `[tts]` settings or makes
  current Silero defaults ambiguous.
- Stop if using two engines introduces a playback race that `OrderedPlayback`
  cannot already represent.
- Stop if supporting more than `ru` and `en` becomes necessary to complete the
  story; that is a later design decision.
