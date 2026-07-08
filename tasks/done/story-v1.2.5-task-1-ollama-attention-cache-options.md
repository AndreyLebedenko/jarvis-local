# Task: Ollama attention and cache options

**Story:** `tasks/story-v1.2.5-tts-engine-foundation.md`
**Status:** Completed.
**Release:** v1.2.5

## Summary

Expose Ollama attention and KV-cache request options through Jarvis config so
the TTS spike measures the same runtime contract Jarvis will actually use.

## Current Boundary

- Backend config and payload construction only.
- No TTS engine measurements in this task.
- Do not change default runtime behavior unless the default is already
  verified in `PROJECT.md`.
- If Ollama option names or accepted values are uncertain, verify them before
  implementation and record the result.

## Acceptance Criteria

- [ ] `BackendSettings` supports `flash_attention`.
- [ ] `BackendSettings` supports `kv_cache_type`.
- [ ] `OllamaBackend.build_payload()` includes configured values in
      `options` alongside `num_ctx`.
- [ ] Default config preserves current behavior unless `PROJECT.md` is updated
      with a verified decision to change it.
- [ ] `config.example.toml` documents the fields and candidate values used by
      the spike, such as `q8_0` and any other locally verified value.
- [ ] Config tests cover valid and invalid values without type erasure.
- [ ] Backend payload tests cover all configured options.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Do not run live Ollama/GPU measurements in this task.

## Stop Conditions

- Stop if Ollama does not accept these options per request in the supported
  local version.
- Stop if candidate values have unclear semantics or non-obvious compatibility
  trade-offs.
- Stop if preserving current default behavior conflicts with the measurement
  setup needed for the spike.
