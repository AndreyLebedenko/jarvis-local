# Task v1.6.0-2: Attachment domain plan

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-1.

## Summary

Add the pure attachment planning layer: given file metadata and bytes, it
validates each attachment and produces a deterministic plan for text parts,
current-turn media payloads, user-visible warnings, and clear rejection
messages.

## Context you need

- task-v1.6.0-1 policy: exact formats and limits.
- `src/jarvis/core/lifecycle.py`: `TurnSource` and `ModelRequestInput`
  need future attachment values, but this task should keep lifecycle
  changes minimal.
- `src/jarvis/dialog/backend.py`: media payload construction already
  accepts base64 strings and attaches them to the last user message.
- Existing test style: pure dataclass/function tests in `tests/`.

## Boundary

- Pure Python planning only. No UI endpoint, no JavaScript, no model call,
  no journal writes, no audio decoding yet beyond cheap metadata checks.
- Do not read arbitrary filesystem paths supplied by the browser. The
  planner receives bytes and trusted upload metadata from the transport
  layer.
- Do not introduce `any` or loose untyped dictionaries as the planning
  contract.

## Requirements

- Create typed attachment input/result objects for uploaded filename,
  content type, bytes, detected class, planned model text, planned media,
  warnings, and rejection reason.
- Preserve input order in the plan.
- Reject unsupported formats and policy violations with deterministic,
  user-facing messages.
- Produce a distinct source/input classification that later orchestration
  can map to `TurnSource` and `ModelRequestInput`.
- Keep current-turn media separate from conversation history and from any
  persisted journal media path.

## Acceptance criteria

- [ ] Pure tests cover supported and unsupported file classes, empty files,
      oversize files, mixed accepted/rejected batches, and stable ordering.
- [ ] The planner returns typed results that later tasks can consume
      without re-parsing ad hoc strings.
- [ ] No backend, UI, or journal behavior changes yet.
- [ ] `python -m pytest` and Ruff checks are green.

