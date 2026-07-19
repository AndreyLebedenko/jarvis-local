# Task v1.5.3-7: Docs and release verification

**Status:** Backlog.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** tasks v1.5.3-1 through v1.5.3-6.

## Summary

Record the v1.5.3 architecture in PROJECT.md, finish config/user docs,
and prepare the human-run release checklist that closes the story.

## Context you need

- `PROJECT.md`: per-release architecture entries; task-v1.5.3-2 already
  revised the journal-context contract sentence - verify the final
  wording is consistent with what actually shipped.
- All six task cards of this story and their outcomes.
- `tasks/task-v1.5.2-8-docs-and-release-verification.md` as the shape
  precedent.

## Boundary

- Documentation and verification only; larger findings become bug
  reports, not fixes here.

## Requirements

- PROJECT.md gains an "Architecture v1.5.3" entry: fork contract
  (fork-not-continuation, verbatim text-only tail, budget,
  provenance, source-log immutability), memory files contract
  (locations, caps, injection order, session-start sampling,
  user-edited-only in this release), and the Hidden/locality
  boundaries.
- `config.example.toml` and README reflect the new `[memory]` settings
  and features.
- A consolidated human-run checklist covers the manual handoffs of
  tasks 3 and 6 plus an end-to-end pass: write a fact into memory.md,
  restart, confirm recall in a spoken answer; fork a session and
  confirm contextual continuity; verify the source session unchanged.
- Out-of-scope findings become reports under `tasks/bug_reports/`.

## Acceptance criteria

- [ ] PROJECT.md updated in the same change as the story closure.
- [ ] Human-run checklist executed with results recorded; findings
      filed as reports.
- [ ] `python -m pytest` and Ruff checks are green.
- [ ] Story closure per the task documentation workflow after human
      approval.
