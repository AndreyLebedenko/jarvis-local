# Task v1.8.1-4: Persistent session file upload

**Status:** Completed. Split into 4a (backend) and 4b (UI). Manual handoff run
2026-08-23: mark-persist upload writes a loose session file and surfaces its
storage name to the model, including the first-event-of-a-new-session case;
persistent-save failures stay visible in the dock.
**Story:** `tasks/story-v1.8.1-session-file-operations.md`
**Depends on:** tasks v1.8.1-1 through v1.8.1-3.

## Summary

Let the user mark an uploaded attachment as a persistent session file, copy it
into the current session directory through the repository's generated storage
name scheme, and surface the resulting `storage_name` to the model.

## Context you need

- `tasks/story-v1.8.1-session-file-operations.md`: UI upload seam and the
  rule that storage-name generation lives only in the repository.
- `src/jarvis/ui/transport.py`: `POST /api/journal/input`, multipart upload
  parsing, auth/Hidden checks, attachment response payloads, and journal media
  route behavior.
- `src/jarvis/inputs/attachments.py` and
  `src/jarvis/inputs/attachment_audio.py`: attachment planning classes,
  limits, accepted/warning/rejected result vocabulary, and media class
  detection.
- `src/jarvis/app.py`: `AttachmentSubmissionResult` path from UI transport to
  orchestrator/model input.
- `status_console_ui/`: Journal input dock controls and attachment status
  rendering.

## Boundary

- Persistent upload path only. No per-file delete UI in v1.8.1.
- Do not change the existing transient attachment behavior except where the
  user explicitly marks a file as persistent.
- Do not let client-provided paths or names become storage paths.
- No arbitrary binary write tool for the model; binary persistence is
  UI/internal only.

## Requirements

- Add a UI/transport flag for "persist this attachment as a session file" on
  selected uploads.
- Copy marked upload bytes into the current session through
  `SessionFileRepository.write_bytes()`, using the upload basename only as the
  requested label.
- Surface the returned `storage_name` to the model in the same turn so it can
  later call `read_session_text`, `view_session_image`, `stat_session_file`,
  or pass the handle to future tools.
- Keep transient model media behavior for image/audio attachments intact:
  marking a file persistent must not remove it from current-turn vision/audio
  unless the existing attachment planner rejects it.
- Return structured per-file UI results that distinguish transient-only
  accepted, persistent accepted with `storage_name`, persistent rejected, and
  ordinary planner rejection.
- Respect Hidden mode, auth, request-size caps, attachment-count caps, and
  repository file caps before claiming a persistent write succeeded.
- Ensure persistent loose files are tied to the current journal-visible
  session and are removed by whole-session deletion.

## Acceptance criteria

- [ ] Transport tests cover marked and unmarked uploads, auth failure, Hidden
      rejection, oversize persistent write rejection, invalid upload basename,
      and repository filesystem failure.
- [ ] Tests prove a marked upload is written through `write_bytes()` and returns
      generated `{storage_name, bytes}` without exposing an absolute path.
- [ ] Tests prove client filenames cannot create traversal paths and are never
      used directly as storage names.
- [ ] Tests prove current-turn attachment visibility is preserved when a file
      is also persisted.
- [ ] UI behavior is manually verified: mark a file persistent, submit, see the
      returned storage name/status, then ask the model to list/view/read it.
- [ ] No per-file delete control is added.

## Stop conditions

- Stop if the existing attachment planner cannot carry the persistent marker
  without mixing persistence policy into media classification.
- Stop if preserving current-turn transient media while also persisting the
  same upload requires duplicating large byte payloads in long-lived state.
- Stop if the UI cannot show persistent-write failures without making the
  final turn state ambiguous.

## Verification

- Focused transport and attachment-path tests.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Manual visual/UI handoff in the Status Console.
