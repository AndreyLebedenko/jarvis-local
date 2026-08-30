# Backlog: Remove task-id references from mode-3 production comments

**Status:** Open. Not blocking.
**Source:** `/code-review high` structured review of task-v1.9.0-3's diff
(2026-08-30), finding 6 (CONFIRMED by a Codex second-opinion pass, with one
correction: the review's own "8 occurrences" count was inaccurate against
the current tree - the real count is listed below). One fresh instance of
this same class, introduced later in the same session while fixing a
different finding, was caught by a Codex stop-time review and fixed
immediately (`src/jarvis/app.py`'s busy-race except-Exception comment,
commit `308edaf`) - that one is closed; this backlog item is only about the
remaining, pre-existing occurrences below.

## Summary

CLAUDE.md rule 7.4: "Never reference a bug report, task card, or issue id
from logic code... the reference belongs in those tests, next to the
assertion, not in the code under test." Task-v1.9.0-3's implementation
added several `(story-v1.9.0 task 3)` references directly in `src/jarvis/**`
comments/docstrings instead of only in the tests that reproduce the
behavior.

## Context

Current occurrences (verified against `main` after task-v1.9.0-3 merged,
commit `308edaf`):

- `src/jarvis/app.py:467, 1000, 1241, 1259, 1283, 2059` (6 occurrences)
- `src/jarvis/core/lifecycle.py:124` (1 occurrence, in `ModelRequestStarted`'s
  docstring)
- `src/jarvis/ui/status_console_ui/app.js:202, 521, 3534` (3 occurrences)
- `src/jarvis/ui/transport.py:992` (1 occurrence)
- `src/jarvis/audio/tts.py:372` (1 occurrence)

12 total. (`src/jarvis/journal/recorder.py`'s own instance was already
removed while fixing a different, related finding in the same task.)

## Current Boundary

- Not blocking task-v1.9.0-3, task-v1.9.0-4, or task-v1.9.0-5; explicitly
  deferred by owner decision (2026-08-30) rather than folded into task 3's
  own closing work.
- Comment-only cleanup: no behavior change. Do not touch the code these
  comments sit next to beyond what is needed to reword them.
- Do not remove the underlying explanation, only the task/story-id part of
  it - each comment still needs to justify itself on its own (why this
  code is shaped this way), just without naming the card that motivated it.

## Possible Approaches

- Reword each comment to drop the `(story-v1.9.0 task X)` parenthetical
  while keeping the substantive explanation, matching how
  `src/jarvis/journal/recorder.py`'s own instance was already reworded in
  this same task (see `git log -p` on that file's `record_assistant()` for
  the pattern) and how `run_derivative_pass()`'s docstring in `app.py` was
  reworded when its adjacent bug was fixed.
- Where the comment is otherwise redundant with self-explanatory code
  (CLAUDE.md 7.1), consider deleting it outright instead of just rewording.

## Acceptance Criteria

- [ ] No `story-v1.9.0`, `task-v1.9.0`, or other task/story-id substring
      remains in any file under `src/jarvis/**` (tests are exempt - CLAUDE.md
      7.4 explicitly allows the reference there).
- [ ] Every reworded comment still reads as self-explanatory without the
      removed reference.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green;
      `node --check` on the touched `.js` file(s).

## Stop Conditions

- None expected; this is a pure comment reword with no behavior surface.
  If any occurrence turns out to be load-bearing (e.g. referenced by a
  test's own string match), stop and confirm before changing it.
