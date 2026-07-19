# Task v1.6.0-7: Journal upload API

**Status:** Completed.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-2, task-v1.6.0-6; v1.5.2 text input endpoint
must exist.

## Summary

Expose attachment submission from the Journal input dock through the
existing authenticated local Status Console transport, producing one
attachment turn request for the orchestrator.

## Context you need

- v1.5.2 text input task: reuse the input dock's submit path rather than
  adding a new hotkey or a second chat surface.
- `src/jarvis/ui/transport.py`: existing HTTP endpoints, auth pattern,
  Hidden handling, and journal media serving.
- `src/jarvis/ui/status_console.py`: Status Console API facade and control
  methods.
- task-v1.6.0-2 planner contract and task-v1.6.0-6 orchestrator entry
  point.

## Boundary

- Transport/API only. No JavaScript controls in this task beyond tests
  that pin endpoint contracts if needed.
- Local authenticated transport only; no external upload, no cloud file
  processing, no file:// path access.
- Hidden mode must block attachment submission content from reaching the
  engine, matching the journal privacy boundary.

## Requirements

- Add an authenticated local endpoint or control command for a typed
  message plus zero or more uploaded files from the Journal input dock.
- Enforce request-size and attachment-count limits before reading the
  full request into long-lived state.
- Pass upload bytes and metadata to the attachment planner/orchestrator
  without trusting client-provided paths.
- Return structured per-file results: accepted, warning, rejected, and
  final turn accepted/rejected state.
- Preserve the existing state/control protocol shape where possible.

## Acceptance criteria

- [x] Transport tests cover authorized submission, missing/invalid auth,
      Hidden rejection, oversize request rejection, unsupported file
      response, and a successful mixed attachment request.
- [x] Tests prove uploaded filenames cannot become filesystem traversal
      paths.
- [x] No browser UI behavior changes yet.
- [x] `python -m pytest` and Ruff checks are green.

## Result

- `POST /api/journal/input` keeps the v1.5.2 JSON typed-text contract and also
  accepts `multipart/form-data` for the same local authenticated input surface.
- Hidden mode and token validation run before request body parsing, so hidden
  attachment content cannot reach the planner or orchestrator.
- Multipart upload bytes are streamed through transport guards before they are
  stored in long-lived request state. File bytes count against the attachment
  byte budget; the typed text field does not.
- Client-provided filenames are reduced to safe basenames before planner input.
- Transport returns structured final turn state plus per-file accepted,
  warning, or rejected results. Oversize request paths return JSON 413 rather
  than the default aiohttp HTML body.

