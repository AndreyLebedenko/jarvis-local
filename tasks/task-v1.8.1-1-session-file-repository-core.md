# Task v1.8.1-1: Session file repository core

**Status:** Not started.
**Story:** `tasks/story-v1.8.1-session-file-operations.md`
**Depends on:** nothing; first implementation card of v1.8.1.

## Summary

Introduce the pure session-file repository and `[files]` configuration for
single-session file operations: generated storage names, create-only writes,
typed reads/stat/list/view, caps, deny-list checks, and lifecycle-safe writes
against one current journal-visible session.

## Context you need

- `tasks/story-v1.8.1-session-file-operations.md`: locked decisions,
  especially loose files, `stem-<uuid>.ext` storage identity, `bytes`
  result naming, and text-only model writes.
- `src/jarvis/journal/store.py`: `JournalStore._session_dir()`,
  `write_media()`, `usage()`, `delete_session()`, and `read_session()`.
- `src/jarvis/journal/events.py`: existing relative media-path validation.
- `src/jarvis/ui/transport.py`: `_resolve_journal_media_path()` containment
  pattern; reuse or factor the shared predicate if useful.
- `src/jarvis/core/config.py`, `config.example.toml`, and
  `tests/test_config.py`: section builders, strict unknown-key behavior, TOML
  list parsing, and positive numeric validation style.

## Boundary

- Repository and config only. No builtin tool registration, no app wiring, no
  UI upload path, no inherited read scopes.
- The repository may expose an internal `write_bytes()` for future UI/Kling
  callers, but the model-facing write semantics remain text-only in this card.
- No journal events are appended for loose files. No sidecar manifest or
  original-name storage is introduced.

## Requirements

- Add `SessionFileRepository` and small typed result/error objects in a pure
  module such as `src/jarvis/files/session_files.py`.
- Add `SessionFileScope` with one current write/read session for this card;
  multi-session inheritance is task 2.
- Validate names as storage-name labels: relative, no `..`, no absolute
  paths, no root escape after resolution.
- Generate storage names from requested labels as `stem-<uuid>.ext` or
  `stem-<uuid>` and never write the requested label directly.
- Preserve create-only semantics. If a generated storage name already exists,
  generate another UUID-backed name; never overwrite.
- Implement `write_text`, `write_bytes`, `read_text`, `view_image_bytes`,
  `stat`, and `list` for the current session.
- Enforce config caps: `max_text_write_chars`, `max_text_read_bytes`, and
  `max_image_view_bytes`.
- Enforce `[files].write_ext_blacklist` only on writes, case-insensitive, with
  normalized no-dot tuple storage.
- Allow only PNG/JPEG image view in this repository API.
- Refuse operations with a typed `no_active_session` error when the supplied
  write scope is absent or not journal-visible according to the story
  invariant.

## Acceptance criteria

- [ ] Tests cover invalid names (`..`, absolute paths, root escapes) for write,
      read, view, and stat.
- [ ] Tests prove writes return generated `storage_name` values, preserve
      extensions, create no original-name sidecar/manifest, and never write the
      requested label directly.
- [ ] Tests cover UUID collision handling by forcing a generated name to
      already exist and asserting a fresh name is used without overwriting.
- [ ] Tests cover deny-listed, allowed, mixed-case, and no-extension writes.
- [ ] Tests cover text write/read caps, binary/undecodable text read errors,
      PNG/JPEG image view success, unsupported image formats, and image caps.
- [ ] Tests cover `stat`/`list` metadata including `storage_name`, `bytes`,
      `mtime_utc`, `session_id`, and `scope`.
- [ ] Tests prove loose file writes leave `events.jsonl` unchanged, still count
      in `JournalStore.usage()`, and are removed by `delete_session`.
- [ ] Tests prove file tools do not create a loose-only session directory when
      there is no active journal-visible session.
- [ ] `[files]` config parsing accepts a TOML array of strings, normalizes
      extensions to a tuple without leading dots, rejects non-strings/empty
      extensions, validates positive caps, and is documented in
      `config.example.toml`.

## Stop conditions

- Stop if repository containment cannot share or clearly mirror the existing
  journal media containment rules without a fourth divergent implementation.
- Stop if making loose files count in `JournalStore.usage()` or
  `delete_session()` requires changing journal lifecycle semantics.
- Stop if the no-active-session invariant conflicts with current
  `JournalRecorder` startup behavior in a way this card cannot isolate.

## Verification

- Focused repository and config tests.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
