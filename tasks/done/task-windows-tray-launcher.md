# Task: Windows tray launcher

**Status:** Completed.
**Story:** `story-windows-tray-launcher.md`.

## Summary and current boundary

Deliver the owner's complete tray launcher contract from the story in one
reviewable slice. Include its local icon assets, Settings, desktop shortcut
helper, private runtime control bridge, and verification handoff. Do not
implement workspaces, frozen executable packaging, automatic mode switching,
runtime config migration, or unrelated installer-story steps.

## Acceptance criteria

- [x] Idle tray start and exact Assistant/MCP/Settings/Exit menu implemented.
- [x] Runtime and launcher single-instance protection with styled dialogs.
- [x] Sequential starts and orderly shutdown without killing a process.
- [x] Validated single Home Folder, persisted Touchstrip and live updates.
- [x] Opt-in per-user Windows startup and About.
- [x] Desktop shortcut with icon and no console; multi-resolution tray asset.
- [x] Pure tests and Ruff gates pass; self-contained human handoff prepared.
- [x] PROJECT.md and both READMEs document the delivered behavior.
- [x] Owner review and native verification confirmed on 2026-10-16.

Owner confirmed normal operation after manual verification and explicitly
authorized committing and merging into main on 2026-10-16.

## Implementation and verification (2026-10-16)

- Implementation branch: `codex/windows-tray-launcher`.
- `jarvis.launcher` separates lifecycle/preferences, subprocess adapter,
  startup registration, native tray, and Tk settings. No runtime dependency
  was added. `desktop_control.py` owns the private stdin command protocol.
- Existing `app.py` accepts an optional desktop-control seam; default CLI
  callers retain their existing arguments and lifecycle. The runtime mutex
  is unchanged; only the launcher requests the separate fixed launcher name.
- Built-in ImageGen source and deterministic multi-resolution ICO export
  are under the launcher assets. Generation prompt is recorded in that
  directory's README. No image generation is required at runtime.
- Full suite: 3375 passed, 3 skipped, 36 upstream deprecation warnings,
  102.75 seconds. Two subsequently added entrypoint/functional-action tests
  passed separately (2.08 seconds).
- Final full Ruff check passed; final Ruff format check passed for 322 files,
  including the two added tests. `git diff --check` passed.
- PowerShell syntax checks passed for both new scripts. The icon's PNG
  frames/alpha and common Windows dimensions are covered by a pure file test.
- Desktop shortcut created at
  `C:\Users\adinor\Desktop\Jarvis Launcher.lnk`; native launcher/runtime,
  logon behavior, and visual appearance were not run by the agent. Owner
  subsequently confirmed successful manual verification on 2026-10-16.
- Graphify AST update passed. Its existing metadata JSON zero-node warnings
  and large-graph HTML skip do not affect the runtime or test gates.

## About follow-up (2026-10-16)

Owner requested the GitHub repository link in About. The dialog now displays
`https://github.com/AndreyLebedenko/jarvis-local` as a clickable, keyboard-
accessible link, opening the default browser only on activation. The manual
handoff includes that check. Existing launcher entrypoint/runtime tests:
19 passed (1.74 seconds); project lint and format check passed. Owner included
this addition in the successful manual verification reported on 2026-10-16.
