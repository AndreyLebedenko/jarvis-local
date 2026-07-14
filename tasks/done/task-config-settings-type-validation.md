# Task: Validate types when constructing TTS settings from parsed config

Status: Not started.
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
