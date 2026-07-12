# Task v1.2.15: Fully configurable TTS routes

**Status:** In Progress.
**Release:** v1.2.15
**Role:** Engine prerequisite for the v1.3.0 Control Center

## Summary

Replace the legacy global TTS voice/rate settings and generic engine/model
pair with typed, engine-specific Silero and Piper route configuration. Validate
configuration structure and general sanity at startup, but defer model-file and
engine/model compatibility checks to lazy engine loading. Lazy-load failures
must keep the runtime alive, produce a structured TTS error signal for the UI,
and preserve the detailed exception in stderr.

## Current Boundary

In scope:

- A discriminated, typed route configuration for the two production engines:
  Silero and Piper.
- Silero-specific model, language, speaker, sample-rate, and supported
  synthesis parameters; no project allowlist of Silero model identifiers.
- Piper-specific model/config paths, load options, and the installed Piper
  `SynthesisConfig` parameters.
- Startup validation of required fields, unknown fields, types, and general
  sanity ranges, with `ConfigError` before application construction.
- Removal of the legacy global `[tts].voice` and unused `[tts].rate` contract;
  migration failures must name the replacement route fields clearly.
- Lazy model/voice loading for both engines. Constructors and config parsing do
  not probe the filesystem or invoke a TTS package.
- Offline-runtime preservation: lazy loading must fail clearly when required
  local assets are absent and must not trigger an implicit network download.
- A structured route-load failure signal carrying language, engine, and model
  context. The module-health projection reports load failure as `ERROR`;
  ordinary per-unit synthesis failure remains `DEGRADED`.
- Detailed exception logging to stderr at the engine boundary without silent
  catches. A failed route is not retried repeatedly during the same process.
- Updated `config.example.toml`, `PROJECT.md`, pure tests, and an exact manual
  handoff for real Silero/Piper verification.

Out of scope:

- New TTS engine types beyond Silero and Piper.
- Downloading models during Jarvis runtime.
- Live configuration reload; settings remain restart-to-apply.
- Expanding charset routing beyond the existing `ru`/`en` pair.
- Control Center form changes. v1.3.0 will consume the typed contract after
  this engine prerequisite lands.
- Hardware-dependent synthesis, playback, GPU, or speaker checks by the agent.

## Configuration Direction

```toml
[tts.languages.ru]
engine = "silero"
model = "v3_1_ru"
language = "ru"
speaker = "eugene"
sample_rate = 48000

[tts.languages.en]
engine = "piper"
model = ".local-models/piper/en_US-ryan-low/en_US-ryan-low.onnx"
config_path = ".local-models/piper/en_US-ryan-low/en_US-ryan-low.onnx.json"
use_cuda = false
length_scale = 1.0
noise_scale = 0.667
noise_w_scale = 0.8
normalize_audio = true
volume = 1.0
```

The parser selects the route dataclass from `engine`; parameters belonging to
the other engine are unknown keys and fail at startup. Model identifiers and
engine-specific parameter combinations are not project-allowlisted: the real
engine decides compatibility during lazy load or synthesis.

## Acceptance Criteria

- [ ] `load_settings()` returns typed Silero/Piper route objects and rejects
      missing, unknown, wrongly typed, or generally nonsensical parameters with
      route-qualified `ConfigError` messages.
- [ ] Any non-empty Silero model identifier is accepted by config parsing; the
      hardcoded `SILERO_MODEL` restriction is removed.
- [ ] Legacy `[tts].voice` and `[tts].rate` fail with a direct migration
      message rather than a generic unknown-key error.
- [ ] Both engine adapters perform model/voice loading only on first synthesis
      and cache either the loaded engine or its terminal load failure.
- [ ] Missing local Silero/Piper assets cannot cause a runtime network request.
- [ ] Silero receives its configured model/language/speaker/synthesis values;
      Piper receives its configured load and `SynthesisConfig` values.
- [ ] A lazy-load failure logs the original exception, publishes route context,
      advances ordered playback, and projects TTS health as `ERROR`.
- [ ] A non-load synthesis failure still skips only that unit and projects TTS
      health as `DEGRADED`; later successful synthesis can recover it.
- [ ] Existing route coverage, sentence ordering, language segmentation, and
      offline-runtime tests remain green.
- [ ] `python -m ruff format --check .`, `python -m ruff check .`, and
      `python -m pytest` pass.
- [ ] Manual hardware/live-engine commands are documented for the human and
      are not run by the agent.

## Stop Conditions

- Stop if the installed Silero or Piper API cannot expose an engine-specific
  parameter without untyped parameter bags or runtime monkey-patching.
- Stop if supporting an official Silero model requires permitting an implicit
  network download during Jarvis runtime.
- Stop if route-level load failure cannot be represented through the existing
  health/event architecture without creating a competing UI event authority.
- Stop if backward compatibility requires retaining the global voice/rate
  semantics instead of producing an explicit migration error.

## Manual Verification Handoff

The agent does not run these hardware/live-engine checks. After automated
verification and human code review:

1. Migrate local `config.toml`: remove `[tts].voice`/`rate`, then place the
   Silero speaker and sample rate under `[tts.languages.ru]` as shown above.
2. Cache the selected Silero package if needed:
   `python setup_tts_model.py --language ru --model v3_1_ru`.
3. Run `python manual/manual_check_bilingual_tts_production.py` and confirm
   Russian and English units use their configured engines, parameters, and
   preserve spoken ordering.
4. Temporarily select a missing local model, synthesize one unit, and confirm:
   one detailed stderr traceback, TTS health `ERROR` in the UI, no network
   request, no repeated load attempts for later units, and continued Jarvis
   operation.
