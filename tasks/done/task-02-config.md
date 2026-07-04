# Task: Configuration (config.py)

Status: Completed.

Story: [story-jarvis-v1.0.md](story-jarvis-v1.0.md)

## Summary

Loads and validates settings for the whole app from a single checked-in
config file, and exposes one typed settings object that every other module
takes as a constructor argument. Documented in PROJECT.md's Architecture
v1.0 section as the settings home: model name, hotkeys, VAD/TTS parameters,
loaded once at startup. This module is also the reason CLAUDE.md's "config
parsing" automated-test category is testable in isolation.

Covers: Ollama model name and endpoint, `num_ctx` (default 65536 per
PROJECT.md's verified facts, with the documented `OLLAMA_KV_CACHE_TYPE`/32768
fallback noted as a comment, not auto-applied logic), hotkey bindings,
TTS voice/rate, VAD thresholds and max chunk length (30 s per PROJECT.md),
sound cue file paths, screenshot default mode.

## Current boundary

In scope:

- File format: TOML via the stdlib `tomllib` reader (Python 3.11, no new
  dependency for reading; writing/example file is hand-maintained).
- A documented example config file checked into the repo (e.g.
  `config.example.toml`) covering every setting above with the values from
  PROJECT.md's verified facts as defaults.
- Clear, typed error on a malformed file (bad TOML syntax, wrong value
  type).
- A documented policy for unknown keys (reject with a clear error, so typos
  in the config file are caught rather than silently ignored).
- A documented policy for a missing config file (fall back to in-code
  defaults matching the example file, or fail with a clear message - pick
  one and encode it as the tested behavior).

Out of scope:

- No hot-reload while running.
- No GUI settings editor.
- No secrets/credential handling (everything is local, nothing to protect).

## Dependencies

None (imports nothing from other project modules). Imported by every other
module.

## Acceptance criteria

Automated tests only (pure logic, no hardware):

- A valid example config file parses into the settings object with the
  expected values for every field.
- A malformed file (bad syntax, wrong type for a field) raises a clear,
  typed error rather than a raw parser exception.
- An unknown key raises a clear error (per the documented policy above).
- The missing-file behavior (default fallback or explicit failure, per the
  documented policy above) is exercised and asserted.
- Round-trip check: the checked-in `config.example.toml` itself parses
  cleanly with no errors.
