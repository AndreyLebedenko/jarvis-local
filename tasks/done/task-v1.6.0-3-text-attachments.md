# Task v1.6.0-3: Text attachments

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.0-file-attachments.md`
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

- [x] Pure tests cover UTF-8 text, empty text, undecodable bytes,
      per-file truncation, per-turn truncation, and multiple files.
      `tests/test_attachments.py`: most of the decode/truncate/wrap
      coverage already existed from task-v1.6.0-2 (which implemented
      `_plan_text()` in full, ahead of this task - see Outcome below).
      Added `test_enforces_max_text_files_per_turn` for the previously
      untested per-turn text-file cap, plus a new `compose_turn_text()`
      section covering typed-message-only, attachment-only, mixed
      accepted/rejected batches, and multi-part ordering.
- [x] Tests prove truncation is visible in the model-facing text.
      `test_compose_makes_truncation_visible_in_the_composed_text`
      asserts the truncation marker survives into `compose_turn_text()`'s
      output, not just the per-item `AttachmentPlanItem.text.content`.
- [x] The planner still preserves accepted/rejected attachment order.
      Unchanged from task-v1.6.0-2; `compose_turn_text()` also preserves
      `plan.items` order when joining multiple text parts
      (`test_compose_preserves_plan_item_order_for_multiple_text_parts`).
- [x] `python -m pytest` and Ruff checks are green.
      Full suite: 1028 passed, 1 skipped. Ruff check and format: clean.

## Outcome

task-v1.6.0-2 already implemented the full per-file text pipeline inside
`src/jarvis/inputs/attachments.py` - UTF-8 decode with a clear rejection
on invalid bytes (`_plan_text`), the `[Attached file: X] ... [End of X]`
delimiter (`_wrap_text`), the `MAX_TEXT_CHARS` truncation marker and
`truncated` flag, and the `MAX_TEXT_FILES_PER_TURN` turn cap via
`_check_turn_caps`. That covers this task's first four requirements
almost entirely; the one gap was the turn cap's text-specific test,
closed here.

The one requirement task-v1.6.0-2 explicitly left undone - "Preserve the
user's typed message from the Journal input dock as the lead content
before attached text" - is this task's actual new code: `compose_turn_text
(typed_text, plan)`, added at the bottom of `attachments.py`. It joins the
typed message with every accepted text item's already-wrapped content (in
plan order) via `"\n\n"`, typed text first. Non-text items (image/audio)
and rejected items contribute nothing, since only `AttachmentPlanItem
.text` is consulted. When `typed_text` is empty, it is dropped from the
join instead of leaving a leading blank line.

This stays a pure function with no `jarvis.*` imports beyond the module's
own types, matching the task boundary (no transport endpoint, no UI, no
wiring into `Orchestrator._start_turn()` - that remains task-v1.6.0-6's
job, which will call `compose_turn_text()` to build the outgoing
`history_text`).

**Review fix 1:** `compose_turn_text()` originally filtered on
`item.text is not None` alone, relying on `plan_attachments()`'s current
behavior of never setting `text` on a rejected item as an implicit,
unenforced invariant - the function's own docstring and this card both
say "accepted text attachments." Fixed to filter on
`item.accepted and item.text is not None` directly, so the contract holds
even if a caller (or a future planner change) ever constructs a rejected
item that happens to carry a `text` part. Added
`test_compose_excludes_a_rejected_item_even_if_it_carries_a_text_part`,
which builds such an `AttachmentPlanItem` directly to pin the guard.

Awaiting human review before this card is marked `Completed.` and moved to
`tasks/done/`, per the standard task-card workflow.

