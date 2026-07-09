# Story v1.2.9 Task 1: TTS language config

Status: Completed.

## Summary

Add a small typed configuration shape that can describe which TTS engine and
model path/package to use for Russian and English speech segments.

## Boundary

In scope:

- Extend `config.py` with per-language TTS route settings for exactly `ru` and
  `en`.
- Preserve current Silero-only runtime behavior when no English Piper route is
  configured.
- Add examples to `config.example.toml`.
- Validate unsupported languages and engine names with `ConfigError`.
- Keep config parsing pure and unit-tested.

Out of scope:

- Loading Piper.
- Routing synthesis between engines.
- Downloading models.
- UI editing of this config.

## Acceptance Criteria

- `load_settings()` parses `[tts.languages.ru]` and `[tts.languages.en]`.
- Supported engines are explicit: `silero`, `piper`.
- Defaults are backward-compatible with the current Silero Russian route.
- Missing optional language routes do not break existing config files.
- Unknown languages such as `[tts.languages.de]` fail clearly.
- Unknown engines fail clearly.
- Tests document the accepted config examples and validation failures.

## Notes

The target shape is intentionally close to the spike route:

```toml
[tts.languages.ru]
engine = "silero"
model = "v3_1_ru"

[tts.languages.en]
engine = "piper"
model = ".local-models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
```
