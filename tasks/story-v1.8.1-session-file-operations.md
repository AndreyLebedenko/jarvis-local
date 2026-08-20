# Story: session file operations (v1.8.1)

**Status:** Design fixed, not started.
**Depends on:** nothing. Standalone capability, useful independent of Kling
or any external integration.

## User-facing goal

Give Jarvis a session-scoped file capability the model can use for any
purpose:

- save a file into the current chat session (e.g. a `.md` note or a
  generated result);
- read a text file back from the current session or from a continued
  session's inherited read-only file scope;
- look at an image file from the same readable scope;
- list and stat what is in the readable session-file scope.

Files live in existing per-session directories (`root/<session_id>/`,
`JournalStore`). Writes always go to the current session directory, so usage
accounting and delete-with-session lifecycle stay tied to the session that
created the file. Continued/forked sessions may read inherited file scopes,
but those inherited directories are read-only from the new session.

This is a general-purpose capability; later features (the Kling render PoC)
reuse it, but nothing here depends on them.

## Locked decisions

1. **Loose files, not journal entries.** A model-written file is a plain
   file in the session dir, NOT recorded as a journal event: its content
   never enters the transcript, derived corpus, or semantic index.
   Corollary the user named: such a file is discoverable only by its storage
   name (via `list` or the name returned at write/upload time).
2. **Create-only for the model.** No overwrite, no delete, no rename tool
   exposed to the model. Destructive actions stay in the user's hands (UI).
   The repository never writes the requested name directly. It generates a
   storage name from the requested name as `stem-<uuid>.ext`
   (or `stem-<uuid>` for a no-extension name), checks that it does not
   already exist in the write directory, and returns the actual storage name.
   If the impossible UUID collision happens, it generates a new UUID; it
   never touches an existing file. Reads/stat/view use storage names only.
3. **Write extension deny-list (config).** A config option
   (`[files].write_ext_blacklist`) lists extensions the model may NOT
   create. Deny-list semantics (fails open by design: anything not listed is
   allowed), acceptable because files are written into Jarvis's own session
   dir and never executed by Jarvis, and the user controls the list.
   Case-insensitive. Applies to `write` only - reading/listing an existing
   file is unrestricted. Default list: Windows executable/script extensions
   (`exe bat cmd com scr msi dll ps1 psm1 vbs vbe js jse wsf wsh lnk reg
   sys cpl jar`). A no-extension name is allowed.
4. **Typed read tools, not one polymorphic `read`.** Clearer for a small
   local model; each returns through the right channel.
5. **Write current, read inherited.** A continued/forked session is still a
   new session with its own provenance and lifecycle. Writes always target
   the current session id. Reads/list/stat/view use a runtime-injected
   `SessionFileScope` with `write_session_id` and ordered `read_session_ids`
   (`current` first, then inherited sessions such as `continued_from` and
   ancestors). Inherited scopes are read-only. If there is no active current
   session id (journal disabled, no session has started, or the current
   session is not yet journal-visible with at least one valid event), every
   file tool returns a typed `no_active_session` error rather than creating a
   loose directory. A file write does not force session creation. Inherited
   reads are live pointers, not snapshots: if the user deletes an ancestor
   session, the continued session loses access to its files. Discovering an
   inherited file requires `list` first, since its `storage_name` was never
   surfaced into this session's context.
6. **Generated storage names avoid cross-scope ambiguity.** Because all
   model/user-upload writes use `stem-<uuid>.ext`, normal reads do not need a
   model-supplied session id or an ambiguity-resolution argument. A manually
   created exact duplicate storage name across readable scopes is outside the
   generated invariant; resolution is deterministic by scope order (current
   shadows nearest ancestor), and `list_session_files()` reports the
   originating session/scope so the situation is visible.
7. **Bounded model-facing payloads.** Text writes and text reads are capped
   by config (`max_text_write_chars`, `max_text_read_bytes`) so one tool call
   cannot silently blow up the session directory or the tool-result budget.
   Image view is limited to PNG/JPEG (`.png`, `.jpg`, `.jpeg`) and capped by
   config (`max_image_view_bytes`, default matching the existing attachment
   image cap). The unit asymmetry is intentional: write is capped in chars
   (the model produces a string) and read in bytes (an on-disk file of
   unknown encoding); do not "normalize" one to the other.

## Tool surface (model-facing builtins)

- `write_session_file(name, content) -> {storage_name, bytes}` - text
  (UTF-8) write; create-only; deny-list checked; `name` is the requested file
  label, validated (relative, no `..`, not absolute); storage name generated
  as `stem-<uuid>.ext`. The tool message tells the model that the requested
  name was changed and that future read/view/stat calls must use the returned
  `storage_name`. The `name` argument of `read`/`view`/`stat` below is
  therefore the `storage_name` from a write result or `list`.
- `read_session_text(name) -> string` - text content of a text-class file;
  clear error on a binary/undecodable file (use `stat`/`view` instead).
- `view_session_image(name) -> image result` - returns the image via
  `ToolCallResult.images_b64` (the camera pattern,
  `src/jarvis/tools/builtin.py:105`) so the model sees it next inference;
  supports PNG/JPEG only.
- `stat_session_file(name) -> {storage_name, bytes, ext, session_id, scope}`
  - metadata for any file, including binary the reads cannot return.
  Includes filesystem `mtime_utc` so the model can distinguish recent files.
- `list_session_files() -> [{storage_name, bytes, mtime_utc, session_id,
  scope}]` - find loose files by storage name (decision 1's corollary). For
  an inherited scope the model never witnessed the write, so `list` is the
  entry point that surfaces the `storage_name` to read.

No `sessionId` argument on any tool: session-file scope is ambient runtime
context injected into the provider, never a model-supplied value (a
model-named session id would be a cross-session read/write surface).

## Implementation seam

- Pure module `SessionFileRepository` (proposed
  `src/jarvis/files/session_files.py`) over `root/<session_id>/`: owns
  `SessionFileScope`, name validation, storage-name generation, create-only
  writes, deny-list checks, size caps, typed read/list/stat, file `mtime_utc`,
  journal-visible write-session checks, and image-format validation.
  Reuses the existing containment rather than a 4th copy -
  `_validate_media_path` (`src/jarvis/journal/events.py:145`) plus the
  `resolve()`/`relative_to` boundary of `JournalStore._session_dir`
  (`src/jarvis/journal/store.py:143`) and `_resolve_journal_media_path`
  (`src/jarvis/ui/transport.py:1978`). Factor the shared predicate if needed.
- Builtin tools registered by `BuiltinToolProvider`
  (`src/jarvis/tools/builtin.py`), dispatched in `call_tool`, following the
  `remember`/camera precedents. The provider gains a `SessionFileScope`
  source callable plus a `SessionFileRepository`; wired once in `build_app`.
  The scope resolver reads the current journal session on each call and
  returns no active scope unless `JournalStore.read_session(current).records`
  is non-empty, preventing files-only directories from escaping
  `usage()`/`delete_session()`.
- Inherited scope resolution follows fork provenance in the raw journal:
  starting from the current session, read that session's provenance event(s),
  follow `metadata.continued_from` recursively, skip missing/deleted ancestors,
  and stop at a fixed depth/seen-set boundary so corrupt or hand-edited
  provenance cannot loop forever. Scope is rebuilt on each file-tool call,
  matching the live-pointer decision above.
- Config section `[files]` with `write_ext_blacklist: tuple[str, ...]`,
  `max_text_write_chars`, `max_text_read_bytes`, and
  `max_image_view_bytes`, wired through a dedicated section builder in
  `src/jarvis/core/config.py`. TOML arrays arrive as lists; the builder must
  validate `list[str]`, normalize extensions case-insensitively with no
  leading dot, and store the result as a tuple.
- UI upload: an attachment the user marks is copied into the session dir
  under the same runtime-generated storage name scheme; the model is handed
  the `storage_name`.

## Boundary

- No network, no MCP, no hardware. Pure logic + a temp-dir filesystem in
  tests; the builtin dispatch is pure too.
- No overwrite/delete/rename tools. No auto-journaling of written files.
- No per-file UI delete in v1.8.1. The only destructive user action this
  story relies on is deleting the whole session, which removes the loose
  files with the session directory.
- The model-facing write tool is **text-only**. Binary writes are never
  exposed to the model, but the repository owns an internal
  `write_bytes(scope, name, data) -> storage_name` used by non-model
  callers - the UI / Jarvis multimodal-engine upload path, and later the
  Kling render download (`media_fetch`). Storage-name generation lives only
  in the repository; no external caller reinvents it.
- No arbitrary cross-session access. Read inheritance is determined only by
  trusted runtime fork/continue provenance; the model never supplies session
  ids.
- Loose files with journal-media extensions (`.png`, `.jpg`, `.jpeg`, `.wav`)
  live in the same session directory as event media. Existing authenticated
  journal media routes may serve such files by storage name if their suffix is
  allowed by that route; this is not a transcript/corpus surface, but it is an
  intentional consequence of sharing the session directory.

## Proposed ordered task sequence

1. `tasks/task-v1.8.1-1-session-file-repository-core.md` -
   `SessionFileRepository` single-session core + `[files]` config section:
   name validation, generated storage names, create-only writes, deny-list,
   caps, typed read/list/stat/view against the current session only. Pure
   `python -m pytest`.
2. `tasks/task-v1.8.1-2-session-file-scope-inheritance.md` - ordered read
   scopes, current-shadows-ancestor resolution, read-only inherited dirs, live
   `continued_from` traversal, and the `no_active_session` typed error. Pure
   `python -m pytest`.
3. `tasks/task-v1.8.1-3-session-file-builtin-tools.md` - register the five
   tools, dispatch in `call_tool`, inject scope-provider + repository into
   `BuiltinToolProvider`, wire `build_app` including current/inherited read
   scopes. Pure tests for dispatch/validation; manual handoff for a live model
   actually calling them.
4. `tasks/task-v1.8.1-4-persistent-session-file-upload.md` - mark-attachment
   -> copy into the current session dir using the generated storage-name
   scheme -> surface `storage_name` to the model. UI + transport; manual
   visual handoff.
5. `tasks/task-v1.8.1-5-docs-and-release-verification.md` - update
   `PROJECT.md` with the final session-file architecture, reconcile user docs
   and config examples, and run final release verification.

## Acceptance criteria (tasks 1a/1b, all pure `python -m pytest`)

Bullets tagged `(1b)` belong to the scope-inheritance slice; the rest are
single-session (1a).

- Name validation: `..`, absolute, and root-escaping paths are rejected on
  write, read, view, stat.
- Storage names: writes never use the requested name directly; they return
  `stem-<uuid>.ext` / `stem-<uuid>`, preserve the extension, and expose only
  the generated storage name as the stable file identity. No original-name
  sidecar or manifest is created.
- Deny-list: a listed extension is refused on write (case-insensitive); a
  non-listed and a no-extension name are allowed; the list is config-driven.
- Config: `[files].write_ext_blacklist` accepts a TOML array of strings,
  normalizes to a tuple, rejects non-strings/empty extensions, and validates
  positive size caps.
- Create-only: writing never overwrites; if the generated storage name exists,
  a new UUID-backed name is generated and returned. No delete/overwrite path
  exists.
- (1b) Scope: writes target only `scope.write_session_id`;
  reads/list/stat/view search `scope.read_session_ids` in order; inherited
  scopes are read-only; no active or not-yet-journal-visible current session
  returns a typed error.
- (1b) Inherited scope construction follows `continued_from` provenance live
  on each call, skips missing/deleted ancestors, and terminates on depth or
  seen-set limits.
- Loose: a written file leaves `events.jsonl` untouched (no journal event)
  and is not returned by any transcript/corpus read.
- Typed reads: `read_session_text` returns text for a text file and errors
  on binary or oversize text; `view_session_image` yields bytes for
  `images_b64` for PNG/JPEG only and errors on non-image/oversize images;
  `stat`/`list` report storage name, byte size, mtime, session id, and scope.
- Lifecycle: a file written to an existing current journal session counts in
  `JournalStore.usage()` and is removed by `delete_session` for that current
  session (assert the existing behavior holds). A file tool must not create a
  standalone loose-only session directory when no active, journal-visible
  session exists.

## Model-facing outcome contract (task 2, the result the model actually sees)

Every tool must return a clear, distinguishable result for both its success
and each failure path - the model's reliability depends on getting a correct
`is_error` in each "wrong" case, not a silent or ambiguous one. This forces
a task-1 requirement: `SessionFileRepository` must distinguish the causes
with typed results/exceptions (no-active-session / missing / not-text /
not-image / oversize / deny-listed / invalid-name / FS-failure) so the
builtin dispatch can map each to its own message.

- **Read a file that exists** (`read_session_text`): returns its text.
- **Read a file that is missing**: `is_error`, message names the file as not
  found. (Not a crash, not empty string.)
- **Read a file that exists but is not text**: `is_error`, tells the model to
  `stat`/`view` instead.
- **View an image that exists**: image result via `images_b64`.
- **View a missing / non-image / unsupported-format / oversize file**:
  `is_error`, distinct messages.
- **Create a file whose name is free**: writes it, tells the model that the
  requested name was changed, and returns `storage_name` + byte size.
- **Create a file whose requested name is taken**: still succeeds - the
  requested name is not the storage identity. A fresh UUID-backed storage name
  is generated and returned.
- **Create fails for a real reason** (deny-listed extension, invalid name,
  oversize content, no active session, or an FS-level write failure):
  `is_error`, no file written, no partial file left behind or claimed.
- **`stat` / `list`**: `stat` errors on a missing file; `list` returns a
  (possibly empty) list and never errors on emptiness. Both include scope
  metadata so inherited files are visible as inherited rather than silently
  looking current.
