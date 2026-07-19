# Task v1.6.0-8: Journal attachment UI

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
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

- [ ] Structural/logic tests prove file picker and drag-and-drop handlers
      exist, selected files render with remove controls, and submission
      calls the upload API with text plus files.
- [ ] Tests prove Hidden clears pending selections and prevents submit.
- [ ] Tests prove new visible strings come from `strings.js`.
- [ ] Human-run visual handoff is prepared for both languages and narrow
      desktop width.
- [ ] `python -m pytest` and Ruff checks are green.

