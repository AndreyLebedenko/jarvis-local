# Task v1.6.0-2: Attachment domain plan

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.0-file-attachments.md`
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

- [x] Pure tests cover supported and unsupported file classes, empty files,
      oversize files, mixed accepted/rejected batches, and stable ordering.
      `tests/test_attachments.py`, 24 tests: per-class acceptance, text
      truncation/UTF-8 rejection, unsupported extension (incl. M4A),
      empty file, oversize (image/text bytes, audio duration), corrupt
      audio, content-type mismatch/generic/missing, path-like filename
      normalization, mixed-batch ordering, and every per-turn cap
      (per-class count, total count, combined bytes).
- [x] The planner returns typed results that later tasks can consume
      without re-parsing ad hoc strings.
      `src/jarvis/inputs/attachments.py`: `AttachmentUpload` in,
      `AttachmentPlan`/`AttachmentPlanItem` out - frozen dataclasses only,
      no untyped dicts in the public contract.
- [x] No backend, UI, or journal behavior changes yet.
      New module has zero `jarvis.*` imports (stdlib + the already-declared
      `soundfile` only); `core/lifecycle.py` untouched.
- [x] `python -m pytest` and Ruff checks are green.
      Full suite: 1019 passed, 1 skipped. Ruff: all checks passed.

## Outcome

`src/jarvis/inputs/attachments.py` implements `plan_attachments()`:
extension-first classification, content-type cross-check (generic/missing
types trusted), per-file byte caps, audio duration gate via
`soundfile.info()` (header probe, no waveform decode - stays inside the
"cheap metadata check" boundary), greedy per-turn caps (per-class count,
total count, combined bytes) enforced in upload order, UTF-8 text decode
with the existing clipboard truncation-marker pattern reused, and raw-bytes
pass-through for audio (`PendingAudioMedia`) since normalization is
task-v1.6.0-5's job. Filenames are normalized to a bare basename before
anything else runs, closing a path-string risk for later consumers (e.g.
the journal writer) even though this task never touches a filesystem path
itself.

**Review fix 1:** `_classify()` was returning `attachment_class=None` on a
MIME-mismatch rejection even though the extension had already determined
the class (e.g. `.txt` + `application/pdf`), forcing callers to parse the
rejection message to recover the type. Fixed to keep the extension-derived
class on that path - `None` now means only "the extension itself is
unrecognized." `plan_attachments()`'s dispatch updated to branch on the
reason instead of on the class being `None`. `test_rejects_mismatched_
content_type` extended to pin `attachment_class is AttachmentClass.TEXT`
on the rejected item.

**Review fix 2:** the same gap existed for empty files - the empty-length
check ran before classification, so `empty.txt` was rejected with
`attachment_class=None` despite the extension being recognized. Split the
old combined `_classify()` into `_classify_extension()` (extension only,
the one genuine "class unknown" case) and `_check_content_type()` (MIME
check, now takes the already-known class), and reordered
`plan_attachments()` to classify by extension first, then check emptiness,
then content-type, then size/turn caps - every rejection past the
extension step now carries the detected class. Added
`test_rejects_empty_file_with_unsupported_extension_as_unclassified` to
pin the one remaining legitimate `None` case, and extended
`test_rejects_empty_file` to assert `attachment_class is
AttachmentClass.TEXT`.

Awaiting human review before this card is marked `Completed.` and moved to
`tasks/done/`, per the standard task-card workflow.

