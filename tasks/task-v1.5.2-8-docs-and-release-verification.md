# Task v1.5.2-8: Docs and release verification

**Status:** Backlog.
**Story:** `tasks/story-v1.5.2-journal-ux-pack.md`
**Depends on:** tasks v1.5.2-1 through v1.5.2-7.

## Summary

Record the v1.5.2 architecture in PROJECT.md, bring config/docs up to
date, and prepare the human-run release verification checklist that
closes the story.

## Context you need

- `PROJECT.md`: the "Architecture v1.5.0 (dialog journal)" section is
  the model for a compact per-release architecture entry.
- All seven task cards of this story and their outcomes.
- `tasks/done/` release-verification precedents (e.g. the v1.5.0 story
  closure and `task-v1.6.0-10-release-verification.md`'s shape).

## Boundary

- Documentation and verification only; no code changes beyond fixes the
  verification itself reveals as in-scope one-liners (anything larger
  becomes a bug report per the reporting protocol).

## Requirements

- PROJECT.md gains an "Architecture v1.5.2" entry: text input endpoint
  and turn source, copy controls, screenshot media recording and
  thumbnails, disk usage/deletion contract (manual, whole-session,
  index-consistent, active-session protected at the transport layer),
  and the unchanged privacy/locality boundaries.
- `config.example.toml` documents any new config fields introduced by
  the story (only if some were actually added).
- README/user-facing docs mention the new Journal capabilities where
  the journal is already described.
- A consolidated human-run verification checklist covers the manual
  handoffs of tasks 2, 3, 5, and 7 plus an end-to-end pass: typed turn
  answered aloud, copied, its screenshot thumbnail visible, session
  deleted after the run.
- Any behavior found broken but out of scope becomes a report under
  `tasks/bug_reports/`.

## Acceptance criteria

- [ ] PROJECT.md updated in the same change as the story closure.
- [ ] Human-run checklist executed by the human with results recorded;
      open findings filed as reports.
- [ ] `python -m pytest` and Ruff checks are green.
- [ ] Story card moved toward closure per the task documentation
      workflow (cards to `tasks/done/` after human approval).
