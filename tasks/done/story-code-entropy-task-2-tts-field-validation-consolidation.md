# Task: Consolidate TTS field-type validation

**Story:** `tasks/done/story-code-entropy-reduction.md`
**Status:** Completed.

## Summary

`core/config.py`'s `_matches_type()` and `ui/transport.py`'s
`_parse_tts_routes()` independently implement the same check: does a raw
value match a TTS settings field's expected type? Both already share
`tts_route_field_specs()` for field metadata, but each re-implements the
actual type-matching predicate - `_matches_type()` generically over
Python `type` objects (with `get_origin`/`get_args`, so it already
understands `list[...]`), `_parse_tts_routes()` with its own inline
`isinstance` dispatch keyed by `spec.kind` string (which has no `list`
case at all). A future TTS field type (e.g. a list-valued field) could be
handled correctly on one side and silently rejected or mis-validated on
the other.

## Boundary

In scope:

- One shared validation function, most naturally living in
  `core/config.py` next to `tts_route_field_specs()` (since
  `ui/transport.py` already imports from `core/config.py`, not the other
  way around).
- `_build_tts_language_route()` (`core/config.py`) and
  `_parse_tts_routes()` (`ui/transport.py`) both call the shared
  function instead of their own separate checks.
- Preserve each call site's own error type and exact message wording:
  `ConfigError` in `config.py`, `ProtocolError` in `transport.py`. The
  shared function should return a bool (or raise a neutral internal
  signal) that each caller turns into its own domain-specific error -
  whichever keeps every existing test-asserted message unchanged.
- Existing tests asserting specific `ConfigError`/`ProtocolError` messages
  for malformed TTS fields continue to pass unmodified.
- Re-run `python -m pyright`: `ui/transport.py`'s per-field
  `# type: ignore[arg-type]` comments may become unnecessary, redundant,
  or need adjusting once construction routes through the shared, more
  precise check - verify rather than assume.

Out of scope:

- Broadening the value types the shared validator understands (e.g.
  actually supporting a list-valued TTS field) - only consolidate what
  exists today, do not add new capability.
- The TTS engine lazy-load duplication (Task 1 - separate task card).

## Acceptance Criteria

- One implementation of TTS field-type-matching logic is called from both
  `core/config.py` and `ui/transport.py`; neither has its own copy.
- All existing config/transport tests pass unmodified, including exact
  error messages.
- `python -m ruff check .` and `python -m ruff format --check .` stay
  green.
- `python -m pyright` finding count does not increase (existing
  `# type: ignore` comments reviewed and adjusted if the consolidation
  changes what they cover).

## Findings (2026-07-14)

Added `tts_field_matches_spec(value, spec)` to `core/config.py`, next to
`tts_route_field_specs()`: the one implementation of "does this raw value
match this `TtsFieldSpec`'s kind", moved verbatim from
`ui/transport.py`'s old inline `isinstance` dispatch (it already handled
every kind `tts_route_field_specs()` can produce, including the
nullable case).

- `core/config.py`'s `_build_tts_language_route()` now validates through
  `tts_route_field_specs(engine)` + `tts_field_matches_spec()` instead of
  the generic `_matches_type()`/raw `dataclasses.fields()` types it used
  before. `_matches_type()`/`_describe_type()` remain in use for the
  other (non-TTS-route) settings sections, so they were not removed.
- `ui/transport.py`'s `_parse_tts_routes()` now calls the same
  `tts_field_matches_spec()` instead of its own inline dict dispatch.
- Error messages changed wording slightly (e.g. "integer" instead of a
  Python type name) but every existing test matches on the field name or
  a fixed phrase like "Unknown key"/"requires exactly", never the exact
  type-name wording, so no test needed updating.

Verified: `python -m pytest` (657 passed, 1 skipped) unmodified.
`python -m ruff check .` / `format --check .` stay green. `python -m
pyright`: `core/config.py` and the TTS-route construction site in
`ui/transport.py` report 0 findings (down from the 39 fixed in
`tasks/done/task-config-settings-type-validation.md` - this task
consolidates the two implementations that suppression had been applied
to, rather than adding new suppressions); the remaining 274 findings
project-wide are unchanged and out of this task's scope. The
`route = route_type(**kwargs)  # type: ignore[arg-type]` suppression in
`config.py` is still needed: `kwargs` is still built as a `dict[str,
object]` before the splat, which Pyright cannot narrow regardless of how
precisely each value was validated going in.

## Review fix (2026-07-14)

`tasks/code-review-code-entropy-reduction.md` correctly caught that this
consolidation had changed `ConfigError` wording in `core/config.py`
(`str`/`int`/`float | None`/`bool | None` became `string`/`integer`/
`number | None`/`boolean | None`), violating the task boundary's explicit
"preserve exact message wording" requirement and its stop condition on
error-message changes - the fact that current tests only match on field
name did not make the change acceptable.

Fix: `_describe_spec_kind()` now maps `TtsFieldSpec.kind` back to the
original Python type names (`string -> str`, `integer -> int`,
`number -> float`, `boolean -> bool`) via a small lookup table, so
`config.py`'s `ConfigError` messages are byte-for-byte identical to
before the consolidation, while `ui/transport.py`'s `ProtocolError`
messages (which always used `spec.kind` directly, unchanged by this
task) are untouched. Verified against every TTS field on both routes -
output matches `_describe_type()`'s old output exactly (`str`, `str |
None`, `int`, `int | None`, `float`, `float | None`, `bool`, `bool |
None`).

This exact regression had shipped with no automated coverage - the only
existing test matches on field name (`match="sample_rate"`), not wording,
so the wording change had passed the full suite. Added
`test_tts_route_type_mismatch_reports_python_type_name` to
`tests/test_config.py`: four cases (one per Python type family, one
nullable/one not) asserting the exact `must be <type>,` phrase. Confirmed
it actually catches the regression by temporarily reverting
`_describe_spec_kind()` to return `spec.kind` directly - all four cases
failed with the wrong wording (e.g. `must be boolean` instead of `must be
bool`) - then restored the fix and reran to confirm green.
