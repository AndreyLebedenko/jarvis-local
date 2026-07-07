# Story v1.2.3: Hygiene and known debts

**Status:** Completed.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.3

## User-facing goal

Close the small reliability and honesty gaps that can make Jarvis look hung,
misrepresent current privacy limitations, or make local verification harder
than necessary.

## Boundaries

- This release is for narrow fixes and documentation only.
- Do not start the HotkeyProvider migration here.
- Do not introduce a broad turn watchdog unless the narrow backend completion
  edge case proves insufficient.
- Do not change runtime privacy semantics beyond documentation.

## Acceptance Criteria

- [x] A regression test covers the case where the backend stream ends without a
      final `done: true` chunk.
- [x] The implementation prevents the orchestrator from remaining busy forever
      for that completion edge case.
- [x] README known issues clearly document the current `keyboard` package
      trade-off and Administrator/global hotkey limitations.
- [x] If a local preflight script is added, it uses project-approved commands
      and remains optional convenience, not a second source of truth.
      (Decided not to add one - see task 3's resolution.)
- [x] `python -m pytest` passes.

## Task Card Sequence

1. Backend stream completion reliability.
   - Write the failing regression test first.
   - Fix only the confirmed busy-stuck path.
   - See `tasks/done/story-v1.2.3-task-1-backend-stream-completion.md`.

2. README honesty update.
   - Document current global hotkey behavior while `keyboard` remains in use.
   - Keep wording aligned with `PROJECT.md` verified facts.
   - See `tasks/done/story-v1.2.3-task-2-readme-hotkey-honesty.md`.

3. Optional local preflight.
   - Add only if it reduces repeated local command friction.
   - Prefer wrapping existing approved commands over inventing new checks.
   - See `tasks/done/story-v1.2.3-task-3-optional-local-preflight.md`
     (decided not to add - no project-approved formatter/linter exists and
     the only approved command is already a single, trivial invocation).

## Stop Conditions

- Stop if the busy-stuck case cannot be reproduced with a focused pure test.
- Stop if the fix requires a broad orchestration redesign.
- Stop if test failures are caused by infrastructure or hardware dependencies
  outside this release.

## Resolution

All three task cards completed sequentially, each on its own branch, merged
to `main` after each task's local verification:

- Task 1 fixed a real bug: `backend.py`'s `chat()` only published
  `ResponseComplete` from inside the `done: true` branch, so a stream that
  ended without ever sending that chunk left `Orchestrator._busy` `True`
  forever (main.py's `finish_turn()` runs exclusively off that event). Fixed
  by always publishing `ResponseComplete` when the stream ends, with zeroed
  metrics and a logged warning if `done: true` was never seen. Two new
  regression tests confirmed failing before the fix, passing after.
- Task 2 was documentation-only: expanded `README.md`/`README.ru.md`'s Known
  Issues to name the `keyboard` package's global-key-hook privacy trade-off
  and the Administrator/elevation mechanism, aligned with `PROJECT.md`'s
  verified facts and pointing at the future `HotkeyProvider` migration
  (v1.2.6) without promising it or any other platform.
- Task 3 was decided against: no project-approved formatter/linter exists
  in this repo, and the only approved local command (`python -m pytest`) is
  already trivial - a wrapper script would add indirection and risk
  becoming a second, drifting source of truth against `.github/workflows/
  ci.yml`.

`PROJECT.md`'s `backend.py` architecture note was updated in the same
change set as task 1 to record the new completion guarantee.
Final validation: `python -m pytest` passes (269 passed) on `main` after all
three task branches were merged.
