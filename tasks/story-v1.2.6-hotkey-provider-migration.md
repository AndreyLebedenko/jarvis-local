# Story v1.2.6: HotkeyProvider migration release

**Status:** Backlog.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.6
**Detailed story:** `tasks/story-hotkey-provider-migration.md`

## User-facing goal

Remove the privacy and reliability debt from global hotkeys by routing all
shortcut handling through a native provider abstraction instead of the current
global key-hook dependency.

## Boundaries

- The detailed scope lives in `tasks/story-hotkey-provider-migration.md`.
- Windows `RegisterHotKey` is the first provider.
- Linux/X11/Wayland implementation is out of scope.
- Manual global behavior verification remains a human handoff.
- Do not leave the project in a long-lived mixed hotkey model without
  documenting the remaining privacy trade-off.

## Acceptance Criteria

- [ ] `HotkeyProvider` interface contains no Windows-specific details.
- [ ] `WindowsHotkeyProvider` registers concrete combinations with
      `RegisterHotKey`.
- [ ] Registration conflicts produce clear log/UI errors.
- [ ] Screenshot full, screenshot region, clipboard submit, mic sleep toggle,
      thinking toggle, shutdown, and future push-to-talk use one provider path.
- [ ] The old `keyboard` dependency is removed, or kept only as an explicit
      fallback with documented privacy trade-off.
- [ ] Callback-thread rules are preserved: callbacks schedule work onto the
      asyncio loop and do not decide engine state themselves.
- [ ] Human handoff verifies global behavior outside Jarvis focus.

## Task Card Sequence

1. Provider interface and Windows implementation.
   - Define provider contract.
   - Implement registration, unregistration, and conflict reporting.

2. Migrate existing hotkeys.
   - Move each current listener to the provider path.
   - Preserve injectable test seams.

3. Dependency and documentation cleanup.
   - Remove or explicitly document `keyboard` fallback.
   - Update README known issues if the privacy state changes.

4. Manual verification handoff.
   - Administrator behavior.
   - Focus-independent hotkeys.
   - Conflict handling.

## Stop Conditions

- Stop if the provider abstraction cannot support existing hotkey lifecycle
  semantics without duplicating listener logic.
- Stop if a current hotkey depends on behavior that `RegisterHotKey` cannot
  represent.
- Stop if migration creates a circular dependency between input modules and
  main runtime wiring.
