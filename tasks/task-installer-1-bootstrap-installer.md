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
clone or unpacked archive: `install.cmd`. It installs missing prerequisites
through winget, creates a project venv, installs dependencies and the package,
copies the example config, pulls every Ollama model the effective config
needs, caches the Silero TTS model, and leaves a committed `Jarvis.cmd`
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
- Missing Python 3.11 and Ollama are installed through winget, not only
  reported.

## Design

### Entry point: `install.cmd` (repo root)

Double-clickable and console-runnable. Runs
`powershell -NoProfile -ExecutionPolicy Bypass -File tools\install\bootstrap.ps1`
with its arguments, scoped to that one process; the machine's execution policy
is not changed. Keeps the window open at the end when double-clicked so the
result can be read.

### Stage 1: `tools/install/bootstrap.ps1` (no Python assumed)

Deliberately thin: only what must happen before a Python 3.11 exists.

1. **winget.** Absent -> stop with the manual install links for Python 3.11
   and Ollama. No other fallback.
2. **Python 3.11.** Detect through the `py -3.11` launcher, then the standard
   per-user install location. Missing -> print the plan and ask for consent,
   then `winget install --exact --id Python.Python.3.11 --scope user`.
   `--scope user` avoids requiring administrator rights. After install,
   resolve the interpreter by explicit path, not `PATH`: the current process
   does not see the updated `PATH`.
3. **Ollama.** Detect `ollama` on `PATH` or at the standard per-user install
   location. Missing -> consent, then `winget install --exact --id
   Ollama.Ollama`.
4. **Consent.** One prompt listing every winget install about to happen.
   winget shows its own package agreements interactively; the installer adds
   `--accept-package-agreements --accept-source-agreements` only under the
   explicit unattended switch `-Yes`.
5. **venv.** Create `.venv` in the app home with the resolved 3.11 if absent.
   An existing `.venv` with another Python version stops the run with a
   message; the installer never deletes it.
6. Hand off to stage 2 with `.venv\Scripts\python.exe tools\installer.py`.

### Stage 2: `tools/installer.py` (Python, testable)

Ordered steps. Each step first checks whether its result already exists and
reports "done" or "skipped (already present)". The first failing step stops
the run with the step name and the exact command to retry; re-running
`install.cmd` resumes from there because every step is idempotent.

1. **Dependencies.** `pip install -r requirements.txt`, then
   `pip install -e .`.
2. **Config.** Copy `config.example.toml` to `config.toml` only if
   `config.toml` does not exist. Never overwrites.
3. **Model inventory.** Load the effective settings through
   `jarvis.core.config.load_settings` (reusing its validation; no second
   parser) and collect every Ollama model they reference: `[backend].model`,
   and `[history.semantic].model` when `[history.semantic].enabled`. The
   collection is one function with a test, so a future model-bearing setting
   has one place to be added.
4. **Ollama reachability.** Query `[backend].endpoint`. Unreachable -> stop
   with "start Ollama, then re-run install.cmd". The installer does not start
   or manage the Ollama service.
5. **Model pull.** For each inventoried model absent from the endpoint's model
   list, run `ollama pull <model>`; present models are skipped.
6. **Silero.** For each configured Silero route whose model is not cached, run
   `setup_tts_model.py --language <lang> --model <model>`. Piper routes are
   reported as a manual step when their model file is missing; Piper downloads
   are out of scope.
7. **Summary.** What was done, what was skipped, and how to start Jarvis
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
- [ ] On a machine without Python 3.11 and/or Ollama, the installer installs
      them through winget after one consent prompt, without administrator
      rights for Python, and continues in the same run.
- [ ] Re-running `install.cmd` on a complete installation changes nothing and
      reports every step as already done.
- [ ] After a failure in any stage-2 step, re-running resumes and completes.
- [ ] `config.toml` and an existing `.venv` are never overwritten or deleted.
- [ ] Both default Ollama models are pulled; a model already present is not
      pulled again.
- [ ] Automated tests cover the stage-2 logic with fakes: step ordering and
      stop-on-failure reporting, idempotency checks, config copy never
      overwriting, the model inventory from settings (including semantic
      disabled), pull skipping for present models, and command construction.
      No test runs pip, winget, Ollama, or the network.
- [ ] README "Installation" leads with `install.cmd` and `Jarvis.cmd`; the
      manual steps remain as a fallback and gain the missing
      `pip install -e .` and embedding-model pull.
- [ ] Human-run handoff prepared per the Testing protocol (item 4), covering
      the clean-clone path, the re-run path, and the winget path.

## Verification notes

- Automated: `python -m pytest`, `ruff check`, `ruff format --check`.
- Human-run: everything touching winget, pip, Ollama, and Silero downloads.
  The winget path needs a machine or account without Python 3.11 and Ollama.
  Windows Sandbox ships without winget, so it is not a drop-in clean machine;
  the handoff must name what the owner can realistically use. A separate
  Windows user account is the likely candidate: both the `--scope user`
  Python and the Ollama installer are per-user, so that account starts
  without either. The owner's own Ollama server must be stopped first, since
  both would listen on the same default port; the handoff has to confirm
  this on the real machine rather than assume it.
