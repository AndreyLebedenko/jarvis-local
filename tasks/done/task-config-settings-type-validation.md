# Task: Validate types when constructing TTS settings from parsed config

Status: Completed.
Origin: Pyright advisory evaluation,
`tasks/done/story-quality-task-8-advisory-tool-evaluation.md`.

## Summary

Pyright's advisory run against the final `src/jarvis` layout found ~28 real
(non-noise) findings concentrated in `src/jarvis/core/config.py` and
`src/jarvis/ui/transport.py`: `TtsLanguageSettings` and sibling TTS settings
dataclasses are constructed directly from a raw, loosely-typed
(`object`/`Any`) parsed-config mapping, with no field-level type check at
the construction site. A malformed value (wrong type in TOML or in a
transport JSON payload) currently surfaces only as an unhandled `TypeError`
deep inside TTS code at first use, not at load time.

## Boundary

In scope:

- `src/jarvis/core/config.py`: the functions that build
  `TtsLanguageSettings` (and sibling settings dataclasses) from the raw
  config mapping - add explicit per-field type validation/casting at the
  parsing boundary, raising a clear config error at load time instead of
  deferring to a runtime `TypeError`.
- `src/jarvis/ui/transport.py`: the equivalent settings reconstruction from
  a transport JSON payload (same dataclasses, same gap).
- Pure tests covering: a malformed field type in config/payload produces a
  clear load-time error identifying the field, not a deferred crash; a
  well-formed config/payload continues to construct settings exactly as
  before (no behavior change on the valid path).
- Re-run `python -m pyright` on the touched construction sites to confirm
  the findings clear.

Out of scope:

- The remaining Pyright findings from Task 8's evaluation that were
  classified as no-signal: test-double/fixture typing in
  `test_main.py`/`test_ui_transport.py`, ctypes/Win32 stub noise in
  `hotkeys.py`, and asyncio/typeshed strictness quirks. Do not touch these
  as part of this task.
- Any Protocol-based DI redesign for composition-root fakes.
- Any change to the `JSONValue` union type itself in `transport.py`.
- Behavior changes to TTS engine selection, routing, or voice output beyond
  rejecting malformed input earlier.

## Acceptance Criteria

- Constructing TTS settings from a config or payload value with an
  incorrect type raises a clear, load-time error identifying the field and
  expected type, instead of an unhandled `TypeError` at first use.
- `python -m pyright` reports no findings on the touched construction sites
  in `core/config.py` and `ui/transport.py`.
- `python -m ruff check .` and `python -m ruff format --check .` stay
  green.
- `python -m pytest` passes, including new tests for the malformed-field
  case on both the config and transport paths.

## Findings (2026-07-14)

The premise was wrong: both `core/config.py` and `ui/transport.py` already
validate every TTS-settings field before construction and already raise a
clear error identifying the field and expected type.

- `core/config.py`'s `_build_tts_language_route()` calls `_matches_type()`
  per field and raises `ConfigError` before `route_type(**kwargs)`; same
  pattern in `_build_plain_section()`/`_build_tts_section()` for every
  other settings dataclass.
- `ui/transport.py`'s `_parse_tts_routes()` does the equivalent with manual
  `isinstance` checks per field kind, raising `ProtocolError` before
  `TTS_ROUTE_TYPES[engine](**values)`.
- `tests/test_config.py::test_engine_specific_tts_settings_reject_invalid_values`
  already covers exactly the malformed-field scenario this task set out to
  add tests for.

So the acceptance criterion about load-time errors was already met with no
code change. What Pyright actually reports is that it cannot statically
verify a loop-driven, generic validation (`_matches_type` over
`dataclasses.fields()`) narrows `object`/`Any` to each constructor
parameter's exact type - the same class of limitation as ctypes/asyncio
stub noise found elsewhere in the Task 8 evaluation, not a defect.

**Resolution:** no new validation logic added (would have been dead code
duplicating what already exists). Suppressed the 9 affected lines with
`# type: ignore[arg-type]`, matching the pre-existing precedent at
`ui/transport.py`'s `_parse_vad()` (`VadSettings(**kwargs)  # type:
ignore[arg-type]`):

- `core/config.py`: the `_matches_type()`/`_describe_type()` calls and the
  `cls(**kwargs)`-equivalent construction lines in
  `_build_plain_section()` (n/a - generic `cls: type` already types as
  `Any`, no suppression needed there), `_build_tts_section()`, and
  `_build_tts_language_route()`; plus the `_describe_type()` result now
  extracted to a local `description` variable to keep lines under Ruff's
  88-column limit.
- `ui/transport.py`: `TTS_ROUTE_TYPES[engine](**values)` in
  `_parse_tts_routes()`.

Verified: `python -m pyright` findings in `core/config.py` dropped from 23
to 0; the 16 related findings in `ui/transport.py` are also gone (274
total remaining, all previously classified as no-signal or
uncertain-signal in Task 8, none touched by this task). `python -m ruff
check .`, `python -m ruff format --check .`, and `python -m pytest` (657
passed, 1 skipped) all stay green. Task 8's record and PROJECT.md's
quality-tooling contract were corrected to match this finding.
