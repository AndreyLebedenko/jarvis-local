# Story v1.2.6: HotkeyProvider migration release

**Status:** Completed (closed 2026-07-11).
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.6

## User-facing goal

Remove the privacy and reliability debt from global hotkeys by routing all
shortcut handling through a native provider abstraction instead of the current
global key-hook dependency.

Jarvis previously used the Python `keyboard` package for global hotkeys. That
global key hook saw a broader keypress stream than Jarvis needed. Tasks 1-3
replaced it with a native provider that registers only concrete shortcuts;
task 4 completed live verification of that provider.

## Boundaries

- Windows `RegisterHotKey` is the first provider.
- Linux/X11/Wayland implementation is out of scope.
- Manual global behavior verification remains a human handoff.
- Do not leave the project in a long-lived mixed hotkey model without
  documenting the remaining privacy trade-off.
- This migration removes the current global-key-hook dependency and changes
  hotkey callback ownership, but it is not itself the region-select overlay
  threading fix. If `capture.py` still creates a Tkinter overlay from a hotkey
  callback after migration, handle that under
  `tasks/backlog/region-select-overlay-threading.md`.

## Acceptance Criteria

- [x] `HotkeyProvider` interface contains no Windows-specific details.
- [x] `WindowsHotkeyProvider` registers concrete combinations with
      `RegisterHotKey`.
- [x] Registration conflicts produce a clear `HotkeyError`.
- [x] Screenshot full, screenshot region, clipboard submit, mic sleep toggle,
      thinking toggle, and shutdown use the provider path. Future
      push-to-talk is required to use the same path when implemented; it is
      not part of this story.
- [x] The old `keyboard` dependency is removed, or kept only as an explicit
      fallback with documented privacy trade-off.
- [x] Callback-thread rules are preserved: callbacks schedule work onto the
      asyncio loop and do not decide engine state themselves.
- [x] Human handoff verifies all migrated hotkeys outside Jarvis focus without
      Administrator privileges.

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
   - Non-Administrator behavior.
   - Focus-independent hotkeys.
   - Conflict handling.

## Resolved Questions

- No `keyboard` fallback is retained; registration failures are explicit.
- Provider status UI was not required to complete the migration.
- Existing default hotkeys remain unchanged; an occupied combination produces
  a clear conflict error.

## Completion Evidence

- Pure suite passed: 478 tests.
- Human verification confirmed that every migrated hotkey works globally with
  another application focused and without running Jarvis as Administrator:
  full-screen capture, region capture, clipboard submit, microphone
  sleep/wake, thinking on/off, and clean shutdown.
- Duplicate registration produced the expected clear `HotkeyError`.
- Shutdown cleanup unregistered providers without errors or tracebacks.
- The known region-overlay threading debt and DirectX capture capability are
  separate follow-ups and do not block this provider migration.

## Stop Conditions

- Stop if the provider abstraction cannot support existing hotkey lifecycle
  semantics without duplicating listener logic.
- Stop if a current hotkey depends on behavior that `RegisterHotKey` cannot
  represent.
- Stop if migration creates a circular dependency between input modules and
  main runtime wiring.
- Stop if screenshot region selection turns out to require a UI-thread redesign
  inside this task rather than a hotkey-provider migration.
