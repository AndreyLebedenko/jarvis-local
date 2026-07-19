# Task v1.6.0-3: Text attachments

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-2.

## Summary

Implement text attachment normalization: decode selected text files,
apply the configured character/byte policy, and make truncation visible in
the model-facing prompt and UI-facing plan.

## Context you need

- task-v1.6.0-1 policy for text size limits and supported encodings.
- task-v1.6.0-2 typed planner contract.
- `src/jarvis/app.py`: current turns are represented as a single user
  content string plus optional media. Text attachments must join that
  string in a clear, bounded way.

## Boundary

- Text formats only. No image, audio, PDF, DOCX, archive, or Markdown
  rendering beyond treating supported files as plain text.
- No transport endpoint and no UI controls in this task.
- Do not store uploaded text as binary media in conversation history.

## Requirements

- Decode supported text files deterministically, with a clear error for
  undecodable content.
- Add file-name-delimited text sections to the planned model prompt.
- Apply per-file and per-turn text limits from task-v1.6.0-1.
- Mark truncation in both the plan warning and the model-facing content,
  so the model cannot treat partial text as complete.
- Preserve the user's typed message from the Journal input dock as the
  lead content before attached text.

## Acceptance criteria

- [ ] Pure tests cover UTF-8 text, empty text, undecodable bytes,
      per-file truncation, per-turn truncation, and multiple files.
- [ ] Tests prove truncation is visible in the model-facing text.
- [ ] The planner still preserves accepted/rejected attachment order.
- [ ] `python -m pytest` and Ruff checks are green.

