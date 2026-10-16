# Story: Windows tray launcher

**Status:** Completed. Owner verified normal operation and authorized commit
and merge into main on 2026-10-16.

## Goal and agreed behavior

A desktop shortcut starts a lightweight launcher in the Windows notification
area. It waits for an explicit mode choice, including at Windows sign-in.
Right-click menu order: Assistant, MCP, separator, Settings, separator, Exit.
Only one runtime and one launcher may exist in the logon session. Selecting
either mode while a runtime exists explains that the user must first finish
the current runtime; there is no automatic switching or termination.

Settings contains Jarvis Home Folder (one existing installation, with Browse),
Touchstrip, Load at Windows start-up, and About. Touchstrip changes apply live
and persist. Home is the installation, not a workspace, and cannot change
while the launcher's runtime is alive. Autostart starts only the idle launcher.
Exit requests the owned runtime's existing orderly shutdown, waits for it,
then removes the tray icon. It never kills an independently started runtime.

## Architecture and boundaries

- A stdlib-only launcher process owns Tk settings/dialogs and a native Win32
  notification icon. It imports no inference, microphone, or application code.
- A child runs the chosen installation's venv Python with that installation
  as cwd. The existing global runtime mutex remains authoritative, including
  races with CLI starts. A separate fixed launcher mutex prevents duplicate
  tray icons across installations.
- A private inherited stdin pipe carries JSON commands for touchstrip
  visibility and orderly shutdown. EOF requests shutdown if the launcher dies.
  There is no socket, PID file, shared command file, or network capability.
- Launcher preferences live under LOCALAPPDATA/JarvisLauncher/settings.json;
  Windows autostart is the current user's Run registry value. No runtime
  config, workspace, journal, or model location is migrated.
- Existing Jarvis.cmd and CLI launches retain their behavior. A new launcher
  command and a shortcut creation script provide the desktop entry.
- Native tray, WebView, logon, and real runtime checks are human-run only.

## Acceptance criteria

- Recognizable desktop and small-size tray icon; packaged local assets.
- Idle start, exact menu, independent sequential mode runs, clear duplicate
  dialogs, graceful Exit, and no console window via desktop shortcut.
- Folder validation and launching from a foreign cwd; single configured home.
- Persistent live Touchstrip toggle; per-user opt-in autostart; About.
- Pure logic and composition tests, Ruff gates, self-contained manual handoff.

## Ordered implementation

One independently verifiable delivery card, `task-windows-tray-launcher.md`:
preferences and process lifecycle, native tray and settings, runtime command
bridge, icon and desktop entry, tests and manual verification instructions.
Owner review and manual verification completed on 2026-10-16; the delivery
card and this story are closed together.
