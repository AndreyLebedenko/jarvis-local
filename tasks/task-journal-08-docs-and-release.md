# Task journal-08: Documentation, screenshots, release wrap-up

**Status:** Planned.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`
**Depends on:** all previous journal tasks completed and human-verified.

## Summary

Close out v1.5.0: update PROJECT.md and user-facing docs, add Journal
view screenshots, record retention/limitation notes, and prepare the
release.

## Context you need

- Story card acceptance criteria (verify every box is checked or
  explicitly re-scoped by the human).
- `PROJECT.md` structure: architectural decisions and verified facts live
  there and must be updated in the same commit as the change they
  describe (CLAUDE.md rule - here the change is the release wrap-up).
- `docs/screenshots/en` and `docs/screenshots/ru` conventions; README or
  equivalent user docs if they enumerate features.

## Boundary

- Documentation, screenshots, and version/tag housekeeping only. Code
  changes limited to review findings the human explicitly approves
  during final verification.
- Do not start any v1.5.1 work (STT, text input) or create its cards
  here.

## Requirements

- PROJECT.md: journal architecture summary (event log as source of
  truth, derived index, live feed, Hidden behavior, media-over-transport
  decision), plus known accepted limitations (FTS5 Russian stemming, no
  transcripts yet, unbounded disk growth if that is what shipped - see
  below).
- Retention check: if no disk-growth policy was decided during
  implementation, record it as an open question / edge case report per
  the story's stop condition, not silently.
- en/ru screenshots of the Journal view (session list + feed with an
  audio tile, and search results) added under `docs/screenshots/`;
  captured by the human, placed and referenced by this task.
- Move completed journal task cards to `tasks/done/` with status
  `Completed.`; update the story card status; the story card itself
  stays in `tasks/` until the human closes the story.

## Acceptance criteria

- [ ] PROJECT.md updated; no story acceptance box left silently
      unchecked.
- [ ] Screenshots present in both languages and referenced from docs.
- [ ] Retention/limitations recorded (as facts or as an explicit open
      question).
- [ ] `python -m pytest` green on the final state.
- [ ] Release handoff prepared for the human (version bump/tag per
      project convention).
