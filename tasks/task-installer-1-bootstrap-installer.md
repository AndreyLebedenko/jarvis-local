# Task: Installer 1 - bootstrap installer

**Status:** Approved (owner, 2026-09-26). In progress.
**Story:** `story-installer-and-workspaces.md` (task 1 after the 2026-09-26
resequencing).
**Origin:** owner planning dialog, 2026-09-26: users report installation as
inconvenient; the installer is scheduled ahead of the mode-3b spike.
**Depends on:** nothing. Independent of the workspace tasks: until they land,
the launcher starts Jarvis from the app home, which is today's supported
launch directory.
**Kind:** new dev/setup tooling. No change to runtime behavior under
`src/jarvis`.

## Summary

Replace the manual README installation with one command run from an existing
clone or unpacked archive: `install.cmd`. It requires an installed Ollama,
installs a missing Python 3.11 through winget, creates a project venv,
installs dependencies and the package, copies the example config, reports the
Ollama models the effective config needs but Ollama lacks (it does not pull
them), caches the Silero TTS model, and leaves a committed `Jarvis.cmd`
launcher ready to use. Re-running it is safe and resumes after a failure.

## Why this exists

Beyond the number of manual steps, the README path is incomplete (found while
writing this card, commit `2112f5d`):

- It never installs the package itself. `python -m jarvis` from the repo root
  needs `pip install -e .` (src layout, `pyproject.toml`); the README
  "Installation" section does not say so, so a fresh clone following it
  cannot start.
- It pulls only the dialog model. `[history.semantic].model`
  (`blaifa/multilingual-e5-large-instruct:latest` in `config.example.toml`)
  is enabled by default and never pulled; semantic retrieval then silently
  degrades to exact/prefix retrieval, as the config comment says.
- On a clean Windows machine `.ps1` scripts do not run under the default
  execution policy, so any PowerShell-only installer fails on first use.

## Owner decisions (2026-09-26)

- The reported pain is installation, not launching.
- The installer starts from an existing clone or unpacked archive; it does
  not clone.
- ~~Missing Python 3.11 and Ollama are installed through winget.~~ Revised
  the same day, after the first implementation: only a missing Python 3.11
  is installed through winget.
- **Ollama is a requirement** (owner, 2026-09-26, revision): the installer
  checks that it is installed and stops with an error and the download link
  if not. Documentation lists it as a requirement.
- **The installer does not download Ollama models** (owner, 2026-09-26,
  revision). Documentation states that Jarvis is tested with Gemma 4 12B, the
  unified multimodal model, linking the official page
  https://ollama.com/library/gemma4:12b.
- **Default model tag becomes `gemma4:12b`** (owner, 2026-09-26): the
  official Ollama tag replaces `gemma4:12b-it-qat` as `[backend].model`
  default (`BackendSettings`, `config.example.toml`) and in the docs' pull
  command. `PROJECT.md` records the change; historical measurements on
  `gemma4:12b-it-qat` stay as written. This touches `src/jarvis` (one default
  value), an owner-directed exception to "Kind" above. Agent addition within that decision: the installer compares the
  configured models with what Ollama has and lists the missing ones as
  `ollama pull <model>` manual notes, without failing.

## Design

### Entry point: `install.cmd` (repo root)

Double-clickable and console-runnable. Runs
`powershell -NoProfile -ExecutionPolicy Bypass -File tools\install\bootstrap.ps1`
with its arguments, scoped to that one process; the machine's execution policy
is not changed. Keeps the window open at the end when double-clicked so the
result can be read.

### Stage 1: `tools/install/bootstrap.ps1` (no Python assumed)

Deliberately thin: only what must happen before a Python 3.11 exists.
Order and rules as implemented (revised during implementation, 2026-09-26,
after detection on the owner's machine missed a Microsoft Store Python):

1. **Ollama requirement, checked first.** `ollama` on `PATH`, then
   `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`. Not found -> stop with
   "Ollama is required", the link https://ollama.com/download, and "then
   re-run install.cmd". Never installed by the installer.
2. **venv state first.** `.venv\Scripts\python.exe` present and 3.11 ->
   ready; no base Python is searched for or installed. Present but another
   version, or a `.venv` folder without `Scripts\python.exe` -> stop with a
   message; the installer never deletes or modifies an existing `.venv`.
3. **Base Python 3.11, only when the venv must be created.** Probe order:
   `py -3.11` launcher, `python3.11` on `PATH` (Microsoft Store alias),
   `python` on `PATH`, `%LOCALAPPDATA%\Programs\Python\Python311\python.exe`.
   Every candidate is verified by running it with `-c` and requiring 3.11;
   no candidate is ever run without arguments.
4. **winget, only when a base Python is needed and missing.** Absent -> stop
   with the manual Python link. Otherwise one consent prompt listing the
   winget command; `-Yes` skips it and is the only case that adds
   `--accept-package-agreements --accept-source-agreements`. Python is
   installed with `winget install --exact --id Python.Python.3.11 --scope
   user` (no administrator rights). After install, the interpreter is
   re-resolved by explicit path: the current process does not see the
   updated `PATH`.
5. **venv creation** with the resolved Python when step 2 found none.
6. Hand off to stage 2 with `.venv\Scripts\python.exe tools\installer.py`
   from the app home, exiting with its exit code.

### Stage 2: `tools/installer.py` (Python, testable)

Ordered steps. Each step first checks whether its result already exists and
reports "done" or "skipped (already present)". The first failing step stops
the run with the step name and the exact command to retry; re-running
`install.cmd` resumes from there because every step is idempotent.

1. **Dependencies.** `pip install -r requirements.txt`, then
   `pip install -e .`. After the package install the running interpreter
   refreshes its import state (`importlib.invalidate_caches()`,
   `site.addsitedir` on site-packages): an editable install is exposed through
   a `.pth` file, which is read only at interpreter start-up, so without the
   refresh `jarvis` is not importable in the same run (verified in a
   throwaway venv, 2026-09-26).
2. **Config.** Copy `config.example.toml` to `config.toml` only if
   `config.toml` does not exist. Never overwrites.
3. **Model inventory.** Load the effective settings through
   `jarvis.core.config.load_settings` (reusing its validation; no second
   parser) and collect every Ollama model they reference: `[backend].model`,
   and `[history.semantic].model` when `[history.semantic].enabled`. The
   collection is one function with a test, so a future model-bearing setting
   has one place to be added.
4. **Model check, never fails, never pulls.** One query of
   `[backend].endpoint` `/api/tags`. Reachable: each inventoried model absent
   from the list (a name without a tag means `:latest`) becomes a manual note
   with the exact `ollama pull <model>` command. Unreachable: one manual note
   that Ollama is not running at the endpoint, listing `ollama pull` for every
   inventoried model. The installer does not start or manage the Ollama
   service.
5. **Silero.** For each configured Silero route whose model is not cached, run
   `setup_tts_model.py --language <lang> --model <model>`. Piper routes are
   reported as a manual step when their model file is missing; Piper downloads
   are out of scope.
6. **Summary.** What was done, what was skipped, and how to start Jarvis
   (`Jarvis.cmd`).

### Launcher: `Jarvis.cmd` (repo root, committed, static)

Changes to its own directory and runs
`.venv\Scripts\python.exe -m jarvis --status-console` with any extra arguments
passed through. If `.venv` is missing it says to run `install.cmd` first. It
is static and committed, not generated, so the installer never has to decide
whether to overwrite a user-edited file. The workspace task later adds
`--workspace` pass-through without changing this contract.

The launcher exists because the venv changes the launch command; without it
the installer would make starting Jarvis harder than today.

## Boundaries

- No cloning, no self-update, no uninstaller.
- No desktop or Start menu shortcut.
- No GPU driver, CUDA, or VRAM checks. The dependency set is the verified
  CPU torch build (`PROJECT.md`, day-0 environment).
- No change to the Ollama service configuration.
- Existing installations are untouched: a machine that already runs Jarvis
  from a global Python keeps working; the installer does not migrate it.
- The installer's network use is one-time setup. The runtime locality
  contract in `PROJECT.md` is unchanged.
- The workspace tasks of the story are not pulled in.

## Acceptance criteria

- [ ] From a fresh clone in an arbitrary directory (including a path with
      spaces), `install.cmd` produces an installation that `Jarvis.cmd`
      starts, with no other manual step on a machine that already has Python
      3.11 and Ollama.
- [ ] On a machine without Ollama, the installer stops before any other
      action with an error naming Ollama as a requirement and the download
      link.
- [ ] On a machine with Ollama but without Python 3.11 (and without a ready
      `.venv`), the installer installs Python through winget after one
      consent prompt, without administrator rights, and continues in the same
      run.
- [ ] Re-running `install.cmd` on a complete installation changes nothing and
      reports every step as already done.
- [ ] After a failure in any stage-2 step, re-running resumes and completes.
- [ ] `config.toml` and an existing `.venv` are never overwritten or deleted.
- [ ] No Ollama model is ever pulled. Configured models missing from Ollama,
      or all of them when Ollama is not running, are listed in the summary as
      `ollama pull <model>` commands; this never fails the install.
- [ ] Automated tests cover the stage-2 logic with fakes: step ordering and
      stop-on-failure reporting, idempotency checks, config copy never
      overwriting, the model inventory from settings (including semantic
      disabled), missing-model notes for reachable and unreachable Ollama,
      and command construction.
      No test runs pip, winget, Ollama, or the network.
- [ ] README "Installation" leads with `install.cmd` and `Jarvis.cmd`; the
      manual steps remain as a fallback and gain the missing
      `pip install -e .` and embedding-model pull. Ollama is listed as a
      requirement, and the docs say Jarvis is tested with Gemma 4 12B
      (unified multimodal, `gemma4:12b`, official page linked).
- [ ] Human-run handoff prepared per the Testing protocol (item 4), covering
      the clean-clone path, the re-run path, and the winget path.

## Verification notes

- Automated: `python -m pytest`, `ruff check`, `ruff format --check`.
- Human-run: everything touching winget, pip, Ollama, and Silero downloads.
  The winget and Ollama-requirement paths need an account without Python
  3.11 and without Ollama. Windows Sandbox ships without winget, so it is not
  a drop-in clean machine. A separate Windows user account is the likely
  candidate: the `--scope user` Python and the Ollama install are per-user,
  so that account starts without either; the handoff has to confirm this on
  the real machine rather than assume it.
