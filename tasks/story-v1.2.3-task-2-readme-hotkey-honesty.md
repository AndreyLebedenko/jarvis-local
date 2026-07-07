# Task: README hotkey honesty update

**Story:** `tasks/story-v1.2.3-hygiene-and-known-debts.md`
**Status:** Backlog.
**Release:** v1.2.3

## Summary

Document the current `keyboard` package privacy trade-off and Administrator
global-hotkey limitation while the migration has not landed.

## Current Boundary

- Documentation only.
- Do not implement HotkeyProvider here.
- Do not change runtime privacy behavior.

## Acceptance Criteria

- [ ] README known issues mention current `keyboard` dependency.
- [ ] README explains the privacy trade-off: global key hook vs native
      registered shortcut.
- [ ] README explains Administrator/global behavior limitation on Windows.
- [ ] Wording is aligned with `PROJECT.md` verified facts.
- [ ] Wording points toward the future HotkeyProvider migration without
      promising unsupported platforms.

## Verification

- Read edited README files with `Get-Content -Raw -Encoding UTF8`.
- Run `python -m pytest` unless the human agrees to docs-only review.

## Stop Conditions

- Stop if documentation would contradict `PROJECT.md`.
- Stop if the change tries to solve runtime behavior instead of documenting it.
