# Task: Configuration layering contract

**Story:** `tasks/done/story-v1.2.4-status-console-control-plane.md`
**Status:** Completed.
**Release:** v1.2.4
**Depends on:** `tasks/done/story-v1.2.4-task-1-shutdown-control.md`

## Summary

Define and test configuration precedence for built-in defaults, user config,
and UI-written config.

## Current Boundary

- Config contract only.
- Do not build the menu UI in this task.
- Do not implement live reconfiguration.

## Acceptance Criteria

- [x] Config precedence is built-in defaults, `config.toml`, then
      `config.ui.toml`.
- [x] The UI config layer is the only layer intended for Status Console writes.
- [x] Restart-to-apply is recorded in `PROJECT.md`.
- [x] Pure tests cover precedence and missing-file behavior.
- [x] Existing config behavior remains compatible when `config.ui.toml` is
      absent.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if precedence conflicts with existing config loading assumptions.
- Stop if restart-to-apply cannot be expressed without changing live runtime
  behavior.

## Resolution

`config.py`'s `load_settings()` gained a second, optional `ui_path`
parameter (default `DEFAULT_UI_CONFIG_PATH = Path("config.ui.toml")`,
alongside the existing `path`/`DEFAULT_CONFIG_PATH`). Both files are read
via a new `_read_toml_file()` (missing file -> `{}`, malformed TOML ->
`ConfigError`, unchanged from before) and independently validated via a
new `_validate_raw_config()` (unknown section/unknown key -> `ConfigError`,
attributed to whichever file actually contains the problem) *before*
merging - this preserves per-file error attribution instead of only being
able to say "somewhere in the merged result." Merging itself is
per-section, per-key: `{**base_section, **ui_section}`, so a key set in
`config.toml` but omitted from `config.ui.toml` still applies (config.ui.toml
overriding one field must not silently reset the rest of that section to
built-in defaults - explicitly tested).

Restart-to-apply required no new mechanism: `load_settings()` already only
ever runs once at startup, so writing `config.ui.toml` mid-run has no live
effect by construction. Recorded in `PROJECT.md`'s "Architecture v1.2.4"
section (task-2 entry), which also documents `config.ui.toml`'s role as the
only Status-Console-writable layer.

`config.ui.toml` added to `.gitignore` next to `config.toml` (both are
machine-local, never committed).

**Tests added** (`tests/test_config.py`, exercised against the
already-existing `backend.model`/`backend.num_ctx`/`vad` fields - this task
proves the layering mechanism generically, not any new UI-specific field):
missing-ui-file compatibility, ui-overrides-base for the same key, per-key
(not per-section) precedence, ui-file-alone-still-defaults-other-sections,
and unknown-section/unknown-key/malformed-TOML/wrong-type `ConfigError`
cases for `config.ui.toml` specifically. `python -m pytest` passes
(280 passed).

**Code-review update (2026-07-07):** `ui_path`'s default was cwd-relative
and independent of `path`, so a real `config.ui.toml` in the process's
cwd (e.g. left behind after task-4's manual handoff) could silently leak
into any `load_settings(path)` call that omitted `ui_path`. Fixed:
default is now `path.with_name("config.ui.toml")` - see `PROJECT.md`'s
Architecture v1.2.4 section for the full write-up and regression test.
