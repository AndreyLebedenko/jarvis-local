# Task: Migrate existing hotkeys

**Story:** `tasks/story-v1.2.6-hotkey-provider-migration.md`
**Status:** Backlog.
**Release:** v1.2.6
**Depends on:** `tasks/story-v1.2.6-task-1-hotkey-provider-interface.md`

## Summary

Move all existing global hotkeys to the new provider path.

## Current Boundary

- Migrate existing listeners only.
- Preserve existing behavior and test seams.
- Do not add push-to-talk behavior beyond reserving compatibility with the
  future trigger.

## Acceptance Criteria

- [ ] Screenshot full hotkey uses `HotkeyProvider`.
- [ ] Screenshot region hotkey uses `HotkeyProvider`.
- [ ] Clipboard submit hotkey uses `HotkeyProvider`.
- [ ] Mic sleep toggle hotkey uses `HotkeyProvider`.
- [ ] Thinking toggle hotkey uses `HotkeyProvider`.
- [ ] Shutdown hotkey uses `HotkeyProvider`.
- [ ] Callback-thread rule is preserved: callbacks schedule onto the asyncio
      loop and do not decide engine state.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.

## Stop Conditions

- Stop if any current hotkey depends on behavior `RegisterHotKey` cannot
  represent.
- Stop if migration creates circular dependencies between input modules and
  main wiring.
