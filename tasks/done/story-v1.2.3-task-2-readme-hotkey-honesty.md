# Task: README hotkey honesty update

**Story:** `tasks/done/story-v1.2.3-hygiene-and-known-debts.md`
**Status:** Completed.
**Release:** v1.2.3

## Summary

Document the current `keyboard` package privacy trade-off and Administrator
global-hotkey limitation while the migration has not landed.

## Current Boundary

- Documentation only.
- Do not implement HotkeyProvider here.
- Do not change runtime privacy behavior.

## Acceptance Criteria

- [x] README known issues mention current `keyboard` dependency.
- [x] README explains the privacy trade-off: global key hook vs native
      registered shortcut.
- [x] README explains Administrator/global behavior limitation on Windows.
- [x] Wording is aligned with `PROJECT.md` verified facts.
- [x] Wording points toward the future HotkeyProvider migration without
      promising unsupported platforms.

## Verification

- Read edited README files with `Get-Content -Raw -Encoding UTF8`.
- Run `python -m pytest` unless the human agrees to docs-only review.

## Stop Conditions

- Stop if documentation would contradict `PROJECT.md`.
- Stop if the change tries to solve runtime behavior instead of documenting it.

## Resolution

`README.md`'s Known Issues section gained two expanded bullets, replacing
the single terse "Windows global hotkeys require Administrator privileges"
line:

1. The `keyboard` package works as a global key hook (sees the whole system
   keypress stream, filters for bound combinations) rather than registering
   only the concrete shortcuts Jarvis needs with the OS - named as a real
   privacy trade-off, not an implementation detail, and pointed at
   `tasks/done/story-v1.2.6-hotkey-provider-migration.md`'s planned
   `HotkeyProvider`/`RegisterHotKey` migration without promising it has
   landed or that any non-Windows platform is supported.
2. The existing Administrator/elevation limitation, expanded with the exact
   mechanism (`add_hotkey` callbacks only fire while Jarvis's own terminal
   window has focus without elevation) and pointing at `PROJECT.md`'s
   Verified facts entry that this was verified live, matching that file's
   wording rather than restating it independently.

`README.ru.md`'s parallel "Известные Проблемы" section was updated the same
way for consistency between the two READMEs (the Russian README already
mirrors the English one bullet-for-bullet).

No runtime code changed. `python -m pytest` passes unchanged (269 passed) -
this task's diff is documentation-only, run to confirm no accidental drift.
