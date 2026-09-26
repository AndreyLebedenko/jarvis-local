# Handoff: bootstrap installer (task-installer-1)

**Task card:** `task-installer-1-bootstrap-installer.md`.
**Run by:** the owner (human-run: pip, Silero download, the Status Console
window, audio, and optionally winget).
**Shell:** every command below is for Command Prompt (`cmd.exe`), not
PowerShell. Steps that change environment variables affect only the console
window they are typed in; close that window afterwards.

## Preconditions

- The branch `feat/bootstrap-installer` is committed in `D:\AI\Jarvis` (the
  clone in step 1 takes committed content only). If it is not, stop and ask
  the agent to commit it.
- Ollama is installed and its server is running on the default endpoint
  `http://localhost:11434` (`[backend].endpoint` default, `BackendSettings`
  in `src/jarvis/core/config.py`). Check: `curl http://localhost:11434/api/tags`
  prints JSON.
- The installer never pulls Ollama models. The clone's `config.toml` is
  created from `config.example.toml`: `[backend].model = "gemma4:12b"`
  and `[history.semantic].model =
  "blaifa/multilingual-e5-large-instruct:latest"`. Run `ollama list` and note
  which of the two are present; missing ones must show up as manual notes in
  step 6. To launch Jarvis in step 7 the dialog model must exist: either
  `ollama pull gemma4:12b` beforehand, or use the optional step 5.
- Download size: the clone installs its own `.venv` (torch and the other
  dependencies: several GB, 5-20 minutes) and caches the Silero model into
  that venv.

## Scenario A - before installing: refusals

1. Clone into a directory with spaces:
   `git clone --branch feat/bootstrap-installer D:\AI\Jarvis "D:\Temp\Jarvis Install Test"`
2. Double-click `D:\Temp\Jarvis Install Test\Jarvis.cmd` in Explorer.
   Expected: "Jarvis is not installed yet. Run install.cmd first." and the
   window waits for a key.
3. Ollama missing. Open a NEW Command Prompt and hide Ollama from it:
   - `set "PATH=C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0"`
   - `set "LOCALAPPDATA=%TEMP%\jarvis-no-localappdata"`
   - `"D:\Temp\Jarvis Install Test\install.cmd"`
   Expected: `ERROR: Ollama is required but was not found on PATH or at
   ...\jarvis-no-localappdata\Programs\Ollama\ollama.exe. Install it from
   https://ollama.com/download, then re-run install.cmd.`; then
   `echo %ERRORLEVEL%` prints `1`. Nothing was created in the clone (no
   `.venv`). Close this window.
4. Python 3.11 missing and winget unavailable. Open a NEW Command Prompt and
   keep only Ollama visible:
   - `set "OLLAMA_DIR=%LOCALAPPDATA%\Programs\Ollama"`
   - `set "PATH=C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0;%OLLAMA_DIR%"`
   - `set "LOCALAPPDATA=%TEMP%\jarvis-no-localappdata"`
   - `"D:\Temp\Jarvis Install Test\install.cmd"`
   Expected: `Ollama: ...\Programs\Ollama\ollama.exe`, `Python 3.11: not
   found`, then `ERROR: winget is not available, so Python 3.11 cannot be
   installed automatically.` and the python.org link; `echo %ERRORLEVEL%`
   prints `1`; no `.venv` in the clone. (This relies on `where py` finding
   nothing on this machine, as detected during implementation; if a `py`
   launcher exists in `C:\Windows`, Python is found and the step does not
   apply - report that instead.) Close this window.

## Scenario B - fresh install

5. Optional only if you did not pull `gemma4:12b`: copy your own
   configuration into the clone. Your `config.toml` references prompt files
   as `@prompts/...`, which resolve under `.jarvis\` next to the config
   (`prompt_root` in `load_settings`, `src/jarvis/core/config.py`), and
   `.jarvis\` is not in git, so copy it too:
   - `copy D:\AI\Jarvis\config.toml "D:\Temp\Jarvis Install Test\"`
   - `copy D:\AI\Jarvis\config.ui.toml "D:\Temp\Jarvis Install Test\"`
   - `xcopy /E /I D:\AI\Jarvis\.jarvis "D:\Temp\Jarvis Install Test\.jarvis"`
   Your config has a Piper route, `[tts.languages.en]` with
   `model = ".local-models/piper/en_US-ryan-low/en_US-ryan-low.onnx"`, and
   the clone has no `.local-models\` (not in git): step 6 must then show a
   Piper manual note - expected, not a failure.
6. Double-click `D:\Temp\Jarvis Install Test\install.cmd` in Explorer.
   Expected, in order:
   - `Jarvis installer, stage 1 (app home: D:\Temp\Jarvis Install Test)`;
   - `Ollama: C:\Users\...\Programs\Ollama\ollama.exe`;
   - `Python 3.11: C:\Users\...\WindowsApps\python3.11.exe` (or another
     3.11 path), no winget prompt;
   - `Creating virtual environment D:\Temp\Jarvis Install Test\.venv`;
   - pip output, `[done] Install Python dependencies`,
     `[done] Install the Jarvis package`;
   - `[done] Create config.toml`, or `[skipped] Create config.toml (already
     present)` after step 5;
   - `[done] Load settings` - proves the package imports in the same run
     right after its install;
   - `[skipped] Check Ollama models (already present)` if both models are
     present, otherwise `[skipped] Check Ollama models (manual step needed,
     see summary)` with one `Ollama model <name> is not on
     http://localhost:11434. Run: ollama pull <name>` note per missing model;
     no download happens either way;
   - `[done] Cache Silero TTS models (cached v3_1_ru)`;
   - `[skipped] Check Piper TTS models (no Piper routes configured)` with the
     example config, or `(manual step needed, see summary)` plus a note
     naming the missing `.onnx` after step 5;
   - `Installation complete.`, any `Manual steps still needed:` lines, then
     `Start Jarvis with Jarvis.cmd`;
   - the window stays open until a key is pressed.
7. Launch from a foreign directory: in Command Prompt `cd /d C:\` then
   `"D:\Temp\Jarvis Install Test\Jarvis.cmd"`. Expected: the Status Console
   opens; a spoken reply is heard (Silero works from the new venv; with your
   copied config, speak Russian - the English Piper route has no model in the
   clone); `journal` and `logs` folders appear under
   `D:\Temp\Jarvis Install Test\`, not under `C:\`, and nothing new appears
   in `D:\AI\Jarvis\journal`. Close Jarvis.

## Scenario C - re-run, Ollama stopped, failure and resume

8. Re-run from an open console: `"D:\Temp\Jarvis Install Test\install.cmd"`.
   Expected: `Virtual environment: already present (...)`; pip reports
   requirements already satisfied; `[skipped] Create config.toml (already
   present)`; `[skipped] Cache Silero TTS models (already present)`;
   `Installation complete.`; the script does NOT wait for a key at the end
   (a double-click does). Known limitation: started from a PowerShell console
   it also waits for a key.
9. Quit Ollama (tray icon -> Quit Ollama); confirm
    `curl http://localhost:11434/api/tags` fails. Re-run `install.cmd`.
    Expected: completes with exit code 0 (`echo %ERRORLEVEL%` prints `0`);
    `[skipped] Check Ollama models (manual step needed, see summary)`; the
    summary has `Ollama is not running at http://localhost:11434 (...), so its
    models could not be checked. Start Ollama, then run:` followed by an
    `ollama pull` line per configured model. Start Ollama again.
10. Failure and resume: open `D:\Temp\Jarvis Install Test\config.toml` in
    Notepad, add the line `bogus_key = 1` as the very FIRST line, save.
    Re-run `install.cmd`. Expected: `[failed] Load settings: config.toml is
    invalid: Unknown section(s) in ...config.toml: bogus_key`, then `Fix the problem above, then re-run
    install.cmd to resume.`; `echo %ERRORLEVEL%` prints `1`. Remove the line,
    save, re-run: completes as in step 8.

## Scenario D - real winget install of Python (optional; changes the machine)

Needs a Windows account without Python 3.11 but with Ollama (the installer
requires Ollama first). A new local user account starts without both
per-user installs; install Ollama there from https://ollama.com/download
first, and quit your own account's Ollama beforehand, since both would use
port 11434. Confirm on the real machine rather than assume. Windows Sandbox is
not a substitute: it ships without winget.

11. In that account, clone as in step 1 into a directory of that account and
    run `install.cmd`. Expected: `Python 3.11: not found`, the prompt showing
    `winget install --exact --id Python.Python.3.11 --scope user`; answer `n`
    -> `ERROR: Installation declined.` with the python.org link, exit 1.
12. Run again, answer `y`. Expected: winget installs Python without an
    administrator prompt, `Python 3.11: ...\Programs\Python\Python311\python.exe`,
    then the same stage-2 sequence as step 6.

## What to report back

- For each numbered step: pass/fail, and the full console output for any
  failure or any line that differs from the expectation.
- Whether scenario D was run, and if not, why.
- Afterwards `D:\Temp\Jarvis Install Test` can be deleted; it holds its own
  venv, journal, and config and shares nothing with `D:\AI\Jarvis` except
  Ollama models.
