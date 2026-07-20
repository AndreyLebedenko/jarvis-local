# Task v1.6.0-8: Journal attachment UI

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-7; v1.5.2 Journal text input UI must exist.

## Summary

Add the user-facing attachment controls to the Journal input dock: file
picker, drag-and-drop, selected-file list, per-file status, and submission
through the local upload API.

## Context you need

- `src/jarvis/ui/status_console_ui/`: vanilla HTML/CSS/JS, no framework
  or CDN. Existing Journal view style and strings must be reused.
- `tests/test_journal_view_ui.py`: structural UI test style.
- task-v1.6.0-7 upload API response contract.
- Story decision: attachments are added from the Journal input dock, not
  from a new hotkey.

## Boundary

- Journal UI only. No Python transport or planner changes.
- Do not re-layout the whole Journal feed. Extend the reserved input dock
  shape from v1.5.2.
- No broad document preview. Show filenames, sizes, type/status, and clear
  warnings only.

## Requirements

- Add an attach control and drag-and-drop target to the input dock.
- Show selected files with remove controls before submission.
- Submit typed text and selected files together.
- Render accepted, warning, and rejected per-file results from the API.
- Keep Hidden mode privacy behavior: clear selected files and disable
  submission when Hidden is active.
- Add en/ru strings for every new visible label and message.

## Acceptance criteria

- [x] Structural/logic tests prove file picker and drag-and-drop handlers
      exist, selected files render with remove controls, and submission
      calls the upload API with text plus files.
- [x] Tests prove Hidden clears pending selections and prevents submit.
- [x] Tests prove new visible strings come from `strings.js`.
- [x] Human-run visual handoff is prepared for both languages and narrow
      desktop width.
- [x] `python -m pytest` and Ruff checks are green.

## Sprint result

Implemented in `src/jarvis/ui/status_console_ui/`:

- Journal input dock now has an Attach button, hidden multi-file picker,
  drag-and-drop target, selected-file list, remove controls, and per-file
  API result rows.
- Submission keeps the old JSON path for text-only input and uses
  `FormData` only when pending files exist.
- Hidden mode clears selected files, disables input submission controls, and
  still relies on the transport-side hidden guard as the privacy boundary.
- Review fix: request-size rejections return `files: []`; the UI now keeps
  pending file rows removable instead of marking them as already sent.
- Review fix: document-level file drag/drop is guarded with `preventDefault()`
  so dropping a file outside the narrow target, including while Hidden hides
  the dock, cannot navigate the WebView to `file://` content.
- Review fix: rejected file rows stay removable; `sent` now means accepted
  by the server, not merely answered by the server.
- Review fix: after an accepted attachment turn, accepted and warning file
  rows are cleared from the input dock so the UI no longer looks like the
  same file is still pending; rejected rows remain visible and removable.
- Live `journal_event` session selection now treats source `attachment` like
  source `dock`, so the feed can jump to the newly-created attachment turn.
- All new visible strings are in `strings.js` for `en` and `ru`.

Verification run so far:

- `python -m pytest tests\test_journal_view_ui.py` -> 47 passed.
- `python -m pytest tests\test_journal_view_ui.py tests\test_journal_live_ui.py tests\test_ui_i18n.py` -> 84 passed.
- Full sprint gate: `python -m ruff format --check .`,
  `python -m ruff check .`, and `python -m pytest` -> green
  (1162 passed, 1 skipped).

Manual visual handoff passed in task-v1.6.0-10's release checklist: English
and Russian UI, narrow desktop width, selected files, API results, Hidden
clearing, document-level file drop guarding, and completed attachment row
clearing were accepted by the human on 2026-07-20.

