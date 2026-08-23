# Task v1.8.1-3: Session file builtin tools

**Status:** Completed. Manual handoff run 2026-08-23: write/list/read/stat/view
verified working. Edge case noted in
`tasks/bug_reports/session-file-list-surfaces-journal-media.md` (list surfaces
journal event media - kept per story boundary, human-confirmed no arch change).
**Story:** `tasks/story-v1.8.1-session-file-operations.md`
**Depends on:** tasks v1.8.1-1 and v1.8.1-2.

## Summary

Expose the session-file repository to the model as five builtin tools:
`write_session_file`, `read_session_text`, `view_session_image`,
`stat_session_file`, and `list_session_files`.

## Context you need

- `tasks/story-v1.8.1-session-file-operations.md`: model-facing tool surface
  and outcome contract.
- `src/jarvis/tools/builtin.py`: `BuiltinToolProvider`, `remember`, camera
  tool, and `ToolCallResult.images_b64` pattern.
- `src/jarvis/tools/host.py`, `src/jarvis/tools/registry.py`, and
  `src/jarvis/tools/interception.py`: builtin registration, dispatch, tool
  enablement, audit events, and provider identity.
- `src/jarvis/dialog/tool_presentation.py`: how text and image tool results
  are rendered back into model context.
- `src/jarvis/app.py`: `build_app()` composition root, existing
  `journal_recorder` closure pattern, and current/inherited scope injection
  points.

## Boundary

- Builtin registration, dispatch, result mapping, and app wiring only.
- No UI upload path; user-marked persistent files are task 4.
- No new external provider, no MCP dependency, no network.
- Do not add `session_id` to schemas; scope is ambient runtime context only.

## Requirements

- Register all five tools with clear schemas and `data_boundary = local`.
- Inject a `SessionFileRepository` and late-bound scope-provider callable into
  `BuiltinToolProvider`.
- Map repository typed errors to distinct model-facing `is_error` results:
  no-active-session, missing, not-text, not-image, unsupported-format,
  oversize, deny-listed, invalid-name, and filesystem failure.
- Return successful `write_session_file` content that tells the model the
  requested name was changed and includes `{storage_name, bytes}`.
- Return `read_session_text` as text content only, not a JSON wrapper.
- Return `view_session_image` through `ToolCallResult.images_b64`, following
  the camera tool pattern.
- Return `stat_session_file` and `list_session_files` JSON with storage name,
  byte size, mtime, session id, and scope metadata.
- Preserve builtin availability and per-tool enablement behavior from the
  existing builtin provider.

## Acceptance criteria

- [ ] Tests cover successful schema registration for all five tools under the
      builtin provider.
- [ ] Tests cover dispatch success for write, read, view, stat, and list,
      including image results through `images_b64`.
- [ ] Tests cover every repository typed error mapping to `is_error` with a
      distinct useful message.
- [ ] Tests prove no tool accepts or forwards a model-supplied `session_id`.
- [ ] Tests prove builtin tools still flow through the existing dispatch/audit
      path and per-tool disable blocks calls.
- [ ] Tests cover app wiring of repository, config, and current/inherited scope
      provider without forcing session creation.
- [ ] Manual handoff is prepared for a live model turn: write a note, list it,
      read it, stat it, and view a session PNG/JPEG.

## Stop conditions

- Stop if builtin result rendering cannot express both JSON metadata and
  image results without changing `ToolCallResult` semantics.
- Stop if scope-provider construction order requires a broad `build_app()`
  rewrite instead of a small late-bound callable.
- Stop if an unexpected builtin exception can still crash the turn after
  repository errors are mapped.

## Verification

- Focused builtin provider, dispatch, and app-wiring tests.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run manual handoff for live model tool use.
