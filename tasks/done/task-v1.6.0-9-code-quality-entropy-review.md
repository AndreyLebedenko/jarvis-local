# Task v1.6.0-9: Code quality entropy review

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-1 through task-v1.6.0-8 completed and reviewed.

## Summary

Review the completed attachment implementation for code entropy introduced
across planning, normalization, orchestration, transport, journal recording,
and Journal UI layers. Fix real duplicated contracts before release
verification starts.

## Context you need

- `PROJECT.md` section "Code entropy review practice (maintenance)".
- `tasks/done/story-code-entropy-reduction.md`: what counts as entropy and
  what does not.
- All completed v1.6.0 implementation task cards and their diffs.
- Likely attachment seams to compare side by side:
  - text/image/audio attachment validation and result shaping;
  - Python planner output vs transport response payloads;
  - backend media construction vs orchestration media handling;
  - journal media/event representation vs UI attachment rendering;
  - JS upload validation/status rendering vs Python policy enforcement.

## Boundary

- Review and focused refactoring only. No new attachment features, no UI
  redesign, no new supported file formats, no release documentation.
- Extract shared behavior only where an actual invariant or contract is
  duplicated. Do not force abstractions over incidental similarity.
- Preserve user-visible behavior, exception types, event shapes, and error
  messages unless a completed task card explicitly left a bug to fix here.
- If the review finds entropy whose fix would require an architectural
  redesign or behavior change, stop and write a bug report/task follow-up
  instead of folding it into this card.

## Requirements

- Read the completed v1.6.0 diffs and identify duplicated contracts or
  sibling implementations that can drift.
- Record each candidate as one of:
  - real entropy fixed in this task;
  - intentional duplication with reason;
  - out-of-scope follow-up because fixing it changes architecture or
    behavior.
- For each real entropy fix, add or preserve tests that would fail if only
  one side of the duplicated contract changed later.
- Run the standard automated gate after any code change.
- If no entropy is found, update this card with a short "No changes needed"
  note and the evidence reviewed.

## Acceptance criteria

- [x] The attachment implementation has no unaddressed duplicated contract
      known to this review.
- [x] Any refactoring preserves existing behavior and error messages.
- [x] Tests cover every shared invariant extracted or consolidated here.
- [x] Any intentional duplication or deferred entropy is documented with a
      reason and boundary.
- [x] `python -m ruff format --check .`, `python -m ruff check .`, and
      `python -m pytest` are green if this card changes code.

## Sprint review notes

Reviewed the attachment seams across:

- planner policy/result shape (`src/jarvis/inputs/attachments.py`);
- uploaded-audio normalization (`src/jarvis/inputs/attachment_audio.py`);
- orchestration and journal source mapping (`src/jarvis/app.py`);
- transport multipart parsing and response shaping
  (`src/jarvis/ui/transport.py`);
- Journal upload UI rendering (`src/jarvis/ui/status_console_ui/`);
- tests covering planner, backend payloads, transport, runtime state, journal,
  and UI/i18n.

Real entropy fixed:

- `AttachmentClass.value` crosses the Python/JS boundary as
  `payload.files[].class`, and `app.js` renders it through the dynamic key
  `journal_attachment_class_` + value. Added
  `tests/test_ui_i18n.py::test_every_attachment_class_has_a_journal_upload_label`
  so adding a future attachment class requires a matching UI label in the
  catalog.
- Multipart `payload.files[]` order crosses the transport/UI boundary: the UI
  maps API results back onto selected local file rows by position. The mixed
  upload transport test now explicitly asserts response filename order matches
  uploaded part order before checking the full response shape.

Intentional duplication, left in place:

- Transport and planner both reduce uploaded filenames to basenames. This is
  defense in depth across trust boundaries: transport strips browser metadata
  before constructing `AttachmentUpload`, while the pure planner preserves its
  no-path contract for any future caller.
- Transport serializes `accepted|warning|rejected` per-file statuses while JS
  renders those statuses. That status vocabulary is the API boundary, not a
  shared algorithm; transport tests pin the JSON shape/order and Journal UI
  tests pin the renderer.
- JS shows a best-effort pending kind from browser MIME type only for the
  pre-submit label. It deliberately does not mirror Python format policy or
  enforce supported extensions client-side.

No deferred entropy follow-up was found. No behavior or user-facing error
message changed during this review.

Verification:

- `python -m ruff format --check .` -> green.
- `python -m ruff check .` -> green.
- `python -m pytest` -> 1162 passed, 1 skipped.

