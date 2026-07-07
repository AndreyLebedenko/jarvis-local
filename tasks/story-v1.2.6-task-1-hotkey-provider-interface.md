# Task: HotkeyProvider interface and Windows implementation

**Story:** `tasks/story-v1.2.6-hotkey-provider-migration.md`
**Status:** Backlog.
**Release:** v1.2.6
**Detailed story:** `tasks/story-hotkey-provider-migration.md`

## Summary

Introduce the provider abstraction and Windows `RegisterHotKey` implementation.

## Current Boundary

- Interface and Windows implementation only.
- Do not migrate every hotkey in this task.
- Linux/X11/Wayland implementation is out of scope.

## Acceptance Criteria

- [ ] `HotkeyProvider` has no Windows-specific details.
- [ ] `WindowsHotkeyProvider` registers concrete combinations using
      `RegisterHotKey`.
- [ ] Provider supports unregister/cleanup.
- [ ] Registration conflict produces a clear error.
- [ ] Tests cover provider contract with fakes and Windows binding shape where
      possible without real global hotkeys.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Prepare manual notes for real provider behavior, but do not run hardware
  verification in this task.

## Stop Conditions

- Stop if existing hotkey lifecycle cannot be represented by the provider.
- Stop if Windows-specific details leak into caller-facing interface.
