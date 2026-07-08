# Task: Backend generation options

**Story:** `tasks/story-v1.2.5-tts-engine-foundation.md`
**Status:** Backlog.
**Release:** v1.2.5

## Summary

Expose Ollama generation sampling options through typed backend config so
Jarvis can tune response format stability, factual carefulness, and speech
latency without editing code or creating ad-hoc Modelfiles.

This follows the same request `options` path already used for `num_ctx`,
`flash_attention`, and `kv_cache_type`.

## Current Boundary

- Backend config, validation, example config, and payload construction only.
- Preserve current runtime behavior by omitting unset options from the request.
- Do not tune defaults in this task unless `PROJECT.md` records verified local
  measurements for the supported model.
- Do not implement UI controls; Control Center exposure belongs to a later UI
  configuration task.
- Do not change the system prompt in this task.

## Ollama Parameters To Cover

Official Ollama Modelfile/API option parameters relevant to generation:

- `temperature`
- `top_p`
- `top_k`
- `min_p`
- `repeat_penalty`
- `repeat_last_n`
- `seed`
- `num_predict`
- `stop`
- `draft_num_predict`

Existing Jarvis options that must remain supported:

- `num_ctx`
- `flash_attention`
- `kv_cache_type`

## Acceptance Criteria

- [ ] `BackendSettings` exposes typed optional fields for supported generation
      options.
- [ ] `load_settings()` validates option types without `any` or type erasure.
- [ ] Unset options are omitted from `OllamaBackend.build_payload()`.
- [ ] Set options are included under the `/api/chat` request `options` object.
- [ ] Existing defaults are unchanged when config omits the new fields.
- [ ] `config.example.toml` documents the new fields and keeps them commented
      or unset unless a verified project default exists.
- [ ] Tests cover parsing valid values for each option.
- [ ] Tests cover rejecting wrong-type values.
- [ ] Backend payload tests cover representative numeric, boolean/string-list,
      and explicit-zero values.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Do not run live Ollama/GPU measurements in this task.

## Notes

- `temperature` is immediately useful for multilingual speech-markup stability:
  lower values may make the XML-like response contract more predictable, but
  the task should expose the option rather than choose a default.
- `stop` should be represented as a list of strings in project config even
  though Modelfiles specify repeated `PARAMETER stop ...` lines.
- `draft_num_predict` should be supported only if it can be passed through
  safely as an optional integer. Do not add speculative decoding behavior or
  assumptions in Jarvis itself.

## Stop Conditions

- Stop if a parameter's request-time semantics differ from Modelfile semantics
  in the supported local Ollama version.
- Stop if validation requires loose dictionaries or unchecked passthrough.
- Stop if adding the full option set creates a larger config redesign than this
  task allows.
- Stop if choosing defaults reveals non-obvious trade-offs for response
  quality, latency, or markup stability.
