# Plan: task v2.0-7 executed through the Quoroom chat

**Status:** Completed. (2026-10-03)
**Card:** `tasks/task-v2.0-7-refactoring-sweep.md`.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Branch:** `feat/v2.0-7-refactoring-sweep` from `main` (`498da8e`).
**Precedent:** `tasks/done/task-v1.9.1-5-refactoring-and-optimization-sweep.md`.

## Roles

Same as `tasks/done/plan-v2.0-6-chat-execution.md`: `claude-code`
orchestrates, reviews, and commits after the owner's review; `glm` writes
code and tests, one slice at a time, never commits; read-only subagents
review. Slice reports by `--file`, addressed `@claude-code`.

## The rule of this card

Strictly behavior-preserving. A change that alters observable behavior, a
payload or tool-result shape, or a test expectation (other than deleting a
duplicate assertion) is not this card: list it, do not do it.

## Slices

- **S1. Inventory (no code changes).** One table, one row per candidate:
  where (`file:line`), what, proposed action (`resolve` / `carry forward`),
  and for `carry forward` the reason. Inputs:
  - the cleanup candidates listed in the completion notes of
    `tasks/done/task-v2.0-1-*` through `task-v2.0-6-*` (tasks 3-5 list none
    explicitly; check their notes and the code they added anyway);
  - card item 2: grep `src/jarvis/` and `src/jarvis/ui/status_console_ui/`
    for repeated literals of `mcp_canvas`, the speech origin and status
    values, and the run mode;
  - card item 3: every place that decides "is this external" from `source`
    instead of the provenance descriptor;
  - card item 4: repeated test setup in this story's tests (recorded
    `mcp_canvas` event, fake voice-guide service, running test server,
    fake player/backend);
  - card item 5: direct imports of this story's code vs `requirements.txt`.
  Mark every row whose resolution would change a shape or behavior.
- **S2. Production code** - only the rows the orchestrator approves from S1.
- **S3. Tests** - shared fixtures and duplicate-assertion removal, approved
  rows only. Coverage must not drop: a removed assertion names the
  lower-level test that still pins it.

Gates after S2 and S3: `python -m pytest`, `ruff check`,
`ruff format --check`.

## Already decided

- `VoiceGuideQueueChanged.in_flight` is removed in favor of `phase`
  (`phase is not VoiceGuidePhase.IDLE`); every reader moves to `phase`.
  Internal event, not a contract.
- Model-facing shapes stay as they are, even where inconsistent
  (`search_history` `provenance.source_kind` vs `read_history` top-level
  `source_kind`): a tool-result shape change is a contract change.
  Carried forward.
- New telemetry (`skipped_ineligible_count` in
  `_resolve_automatic_retrieval()`) is a new capability. Carried forward.
