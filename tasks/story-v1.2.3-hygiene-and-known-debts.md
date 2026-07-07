# Story v1.2.3: Hygiene and known debts

**Status:** Backlog.
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

- [ ] A regression test covers the case where the backend stream ends without a
      final `done: true` chunk.
- [ ] The implementation prevents the orchestrator from remaining busy forever
      for that completion edge case.
- [ ] README known issues clearly document the current `keyboard` package
      trade-off and Administrator/global hotkey limitations.
- [ ] If a local preflight script is added, it uses project-approved commands
      and remains optional convenience, not a second source of truth.
- [ ] `python -m pytest` passes.

## Task Card Sequence

1. Backend stream completion reliability.
   - Write the failing regression test first.
   - Fix only the confirmed busy-stuck path.

2. README honesty update.
   - Document current global hotkey behavior while `keyboard` remains in use.
   - Keep wording aligned with `PROJECT.md` verified facts.

3. Optional local preflight.
   - Add only if it reduces repeated local command friction.
   - Prefer wrapping existing approved commands over inventing new checks.

## Stop Conditions

- Stop if the busy-stuck case cannot be reproduced with a focused pure test.
- Stop if the fix requires a broad orchestration redesign.
- Stop if test failures are caused by infrastructure or hardware dependencies
  outside this release.
