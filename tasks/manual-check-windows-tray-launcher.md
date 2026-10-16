# Windows tray launcher: human verification

**Status:** Owner verified on 2026-10-16; not run by the agent. Steps 2 and 4
were changed afterwards (Show Touchstrip tray item) and need a human re-run.
**Task:** `task-windows-tray-launcher.md`.
**Base commit:** `0f4464623d6e5985f50bfcaa43cd7cbd05368a56`, plus the task diff.

The owner reported that all checks passed and behavior was normal, including
the About repository link, and authorized committing and merging into main.
The procedure below remains the repeatable verification handoff.

Run these checks on Windows 11, from this updated installed checkout at
`D:\AI\Jarvis`, with its existing Ollama/model/TTS setup. This check does not
install models or change runtime configuration. All WebView, microphone,
speech, hotkey, sign-in, and live backend observations belong to the human.
The launcher is English; Jarvis retains its existing configured UI language.

## Entry points and controls

- `JarvisLauncher.cmd` starts the idle tray. Its source is that file.
- Desktop shortcut: `tools/create_launcher_shortcut.ps1`; target is
  `.venv\Scripts\pythonw.exe -m jarvis.launcher`, with installation cwd.
- Tray labels and order: `MENU_ITEMS` in `tray.py`. Settings labels, Browse,
  Save folder, Touchstrip, Load at Windows start-up, About: `window.py`.
- Default Home is the launcher's own source installation
  (`__main__.py` under `src/jarvis/launcher/`, `main()`). Touchstrip defaults
  to `True` (`LauncherSettings` in `model.py`); do not assume that default
  when testing an existing preferences file.
- End a runtime by closing the **Jarvis - Status Console** title-bar X
  (`LiveStatusConsole.create_windows()` in `app.py`). No hotkey or translated
  button label is required by this handoff. The launcher remains in the tray.
- Persistent Home/Touchstrip and startup diagnostics:
  `%LOCALAPPDATA%\JarvisLauncher\settings.json`, `runtime.log` (the run
  before it is kept as `runtime.previous.log`), `launcher.log`
  (`SettingsStore` in `model.py`, launcher `__main__.py`, `ChildRuntime` in
  `process.py`). No earlier task's undocumented default is needed.

## Procedure

1. Establish the initial state explicitly: close any Jarvis Status Console
   by its X; use Exit on any existing Jarvis launcher tray icon. If a
   separately started headless Jarvis exists, end it through its existing
   terminal before this test. Wait for its process to finish.

2. In PowerShell at `D:\AI\Jarvis`, create/update this installation's desktop
   shortcut:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\create_launcher_shortcut.ps1
   ```

   Double-click **Jarvis Launcher** on the desktop. Expect one recognizable
   icon in the notification area (possibly behind Windows' overflow arrow),
   no console window, no Status Console, and no model/microphone startup.
   Right-click: Assistant, MCP, separator, Show Touchstrip (grayed out while
   idle), Settings, separator, Exit.

3. Open Settings. Use Browse to select `D:\AI\Jarvis`, then Save folder;
   verify the displayed canonical path. Ensure Touchstrip is checked (click
   only if unchecked). Ensure Load at Windows start-up is unchecked (click
   only if checked). Close Settings. Reopen it and verify both states.
   About must show the installed package version and the two mode meanings.
   Its clickable `https://github.com/AndreyLebedenko/jarvis-local` link must
   open the repository in the default browser only when activated.

4. Launch **Assistant**. Expect the normal Status Console and Touchstrip;
   confirm normal assistant operation using your existing local setup.
   While it runs, choose **MCP**, then **Assistant** from the tray. Both must
   show the styled already-running dialog and leave the running mode intact.
   Settings must disable the Home entry/Browse/Save folder during this run.
   In Settings ensure Touchstrip is unchecked: it hides immediately. Ensure
   it is checked: the same panel returns. Close the Touchstrip X; the Settings
   checkbox stays checked (it is the saved start-up preference). Choose
   **Show Touchstrip** in the tray menu (enabled while a run is active): the
   same panel returns and the checkbox and `settings.json` are unchanged.
   Close the Status Console X; wait for that runtime to finish. The tray must
   remain idle and Show Touchstrip grayed out again.

5. In Settings ensure Touchstrip is unchecked. Start **MCP**. Expect the
   existing MCP-mode Status Console/voice-guide status, no microphone input,
   and no visible Touchstrip. Turn Touchstrip on and off in Settings; verify
   live show/hide. Use tray **Exit** while MCP is running. Expect orderly
   shutdown of its windows and then removal of the tray icon. Start the
   launcher again: it must wait, with saved Home and Touchstrip unchecked.

6. Double-click the launcher shortcut again while the idle launcher is
   already running. Expect one styled duplicate-launcher dialog, one tray
   icon, and no runtime. Dismiss the dialog. Exit the launcher.

7. Verify a foreign starting directory:

   ```powershell
   Set-Location C:\
   & D:\AI\Jarvis\JarvisLauncher.cmd
   ```

   Settings must retain `D:\AI\Jarvis`. Choose MCP; verify normal startup
   using that installation's existing configuration. Close its Status Console
   X. In Settings try Browse -> `C:\Windows` -> Save folder: expect an error
   naming the missing installation requirement, with the old saved Home
   preserved. Save the valid Home again. If you have another independently
   installed updated checkout, repeat with its absolute path; do not copy a
   venv to simulate an installation. A second installation is optional: path
   selection, quoting, and child cwd are also covered by pure adapter tests.

8. Verify the shared guard against a direct launch. Leave the launcher idle;
   in another PowerShell window run:

   ```powershell
   Set-Location D:\AI\Jarvis
   .\.venv\Scripts\python.exe -m jarvis --status-console --no-touchstrip
   ```

   Choose MCP in the tray: expect a styled refusal and no second runtime.
   Exit the launcher: the directly started Status Console must remain open.
   Close that console X to finish the direct run.

9. Start the launcher. In Settings ensure Load at Windows start-up is checked.
   Registration source is `StartupRegistration` / `WindowsStartupStore` in
   `startup.py`: HKCU `Software\Microsoft\Windows\CurrentVersion\Run`, value
   `JarvisLauncher`, no mode argument. Exit the launcher, then sign out and
   sign back in when convenient (save other applications first). Expect one
   idle tray icon and no runtime. Open Settings and ensure Load at Windows
   start-up is unchecked to remove registration. Verify it stays unchecked
   after another launcher restart. No administrator privileges are needed.

10. Review icon clarity in both the desktop and small tray sizes, Settings
    layout at your display scaling, readable duplicate dialogs, and the tray
    menu dismissing correctly after clicking elsewhere. Report each failed
    step plus `runtime.log` / `launcher.log` when relevant. These native visual
    checks were confirmed by the owner on 2026-10-16.

## Agent environment record

The shell's `python` alias and the sandboxed venv launch could not start the
Microsoft Store interpreter. The owner explicitly authorized the existing
`.venv\Scripts\python.exe` on 2026-10-16. The exact targeted pytest command
was then run with Codex `require_escalated` approval and started successfully;
subsequent automated checks use that same interpreter and approval mechanism.
The venv was not recreated and no system Python configuration was changed.
