# Task v1.6.1-3: Memory write tools

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.1-builtin-tools-delegated-control.md`
**Depends on:** task-v1.6.1-1 (builtin provider core). Independent of
task 2.

## Summary

Builtin tools that let Jarvis append to or update memory.md and self.md
within their size caps, making "remember this" work by voice. Writes are
audited tool calls; the files stay user-auditable exactly as v1.5.3
left them.

## Context you need

- `src/jarvis/memory/files.py`: `MemoryFileRepository` (atomic write,
  `MemoryFileOverCapError`), `MemoryFileId`, per-file caps from
  `MemorySettings`. This is the only write path; the tools wrap it,
  they do not reimplement it.
- v1.5.3 sampling contract (`tasks/done/task-v1.5.3-4-memory-files-core.md`):
  injection samples files at session start; a mid-session write does
  not change the live system prompt.
- v1.5.3 memory panel and API
  (`tasks/done/task-v1.5.3-5-memory-files-api.md`, `-6`): the UI reads
  through the same repository, so tool writes are immediately visible
  there.
- Cross-cutting rule 7: audited tool path only, size caps, annotations
  augment - the model must never be able to bypass the cap or write
  outside the two files.
- Story design decision: proposed tool shape is one `remember`-style
  tool with a file selector and append/replace mode; finalize the shape
  in this card (record the decision in the card outcome).

## Boundary

- Writes to memory.md and self.md only; the file set is closed. No
  new files, no paths from tool arguments, no deletion tool.
- No change to injection, caps, or the UI. No summarization or
  rewriting of existing content by the system itself - the model sends
  explicit content, the tool stores it.
- Model-initiated reads are not part of this card: the files are
  already injected at session start, and a read-back tool is a separate
  decision if ever needed.

## Requirements

- Append is the primary operation: new content joins the existing file
  with a deterministic separator, validated against the cap as a whole
  (existing + appended). Replace (full-content update) exists for
  corrections; successful replace writes first save one previous version as
  `memory.md.bak` or `self.md.bak` and report the backup path in the tool
  result.
- An over-cap write fails with a tool error stating the file, current
  size, cap, and that the user can prune the file in the memory panel -
  the model can relay "memory is full". Never silent truncation.
- The tool result states that the change takes effect in the system
  prompt at the next session start, so the model does not claim
  instant recall.
- Empty or whitespace-only content to append is rejected as a tool
  error (garbage-write guard).
- Audit events carry which file was written and the size delta in the
  outbound summary; content itself appears in arguments as usual (the
  journal already records turns, this adds no new exposure class).

## Acceptance criteria

- [x] Tests cover: append to an empty and a non-empty file (separator
      correctness, UTF-8 Russian content), replace with a one-step `.bak`
      backup, over-cap append and over-cap replace both failing with the
      informative error and leaving the file and backup unchanged,
      empty-content rejection, and that writes go through the injected
      repository seam (no direct file IO in the tool).
- [x] A human-run handoff scenario exists: "запомни, что ..." by
      voice, then verify the fact is in memory.md via the memory panel
      and that the next session's Jarvis knows it.
- [x] `python -m pytest` and Ruff checks are green.

## Implementation outcome

Tool shape decision: one `remember` tool with `file = memory|self`,
`mode = append|replace`, and `content`. Append joins non-empty files with
one blank line. Replace goes through `MemoryFileRepository.replace_with_backup`
so cap checks, the one-step `.bak` file, and atomic writes stay centralized.
Successful replace results mention the `.bak` file in `content` and expose it
as `structured_content.backup`.

Automated verification: `python -m ruff format --check .`,
`python -m ruff check .`, and `python -m pytest` are green.
