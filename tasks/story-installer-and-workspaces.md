# Story: Installer and workspaces

**Status:** Approved (owner, 2026-09-26). Active: scheduled ahead of
`spike-single-pass-tts-block.md` (owner, 2026-09-26: users report installation
as inconvenient). Task 1 (`task-installer-1-bootstrap-installer.md`)
completed 2026-09-27; tasks 2-6 not opened yet.
**Created:** 2026-09-26.
**Origin:** owner planning dialog, 2026-09-26 ("is there an installer, so
Jarvis can be deployed into any directory?"), which grew into per-project
workspaces.
**Target:** not assigned a version.

## User-facing goal

1. Deploy Jarvis into any directory with one bootstrap command instead of the
   manual README steps.
2. Run Jarvis against a chosen **workspace**: a directory that owns its own
   journal and logs, so different projects or life areas keep separate
   conversation histories. Whether a workspace shares memory with others is
   the user's per-workspace choice.

## Current state (2026-09-26, commit `df0ba1d`)

- There is no installer. Deployment is the README "Installation" section:
  clone, `pip install -r requirements.txt`, `ollama pull`, `python
  setup_tts_model.py`, optionally copy `config.example.toml` to `config.toml`.
- The clone location is already free: `src/` contains no absolute paths.
- The launch directory is not free. The app must start with the repo root as
  its working directory, because path-valued settings resolve against the
  process cwd:
  - `DEFAULT_CONFIG_PATH = Path("config.toml")` in `core/config.py`;
    `config.ui.toml` is read next to the config file (`load_settings`);
  - `[sounds]` defaults (`sounds/*.wav`), `[journal].root = "journal"`,
    `[logs].directory = "logs"`, `[memory].root = "memory"` in
    `core/config.py`;
  - Piper `config_path`, `espeak_data_dir`, `download_dir` when relative.
- Precedent for non-cwd resolution already exists: file-referenced prompts
  resolve against `<config dir>/.jarvis` (`prompt_root` in `load_settings`).
- Silero looks for `latest_silero_models.yml` in the process cwd inside the
  library itself; `_ensure_model_cached` in `audio/tts_silero.py` fails loudly
  (`TtsModelNotCachedError`) when cwd lacks it. It does not reach the network.
- There is no CLI option to choose a config file or a workspace (`parse_args`
  in `app.py`).
- Launched from a foreign cwd today, Jarvis does not get "a separate journal";
  it silently runs on default settings, without sound cues, and fails TTS
  start-up. The accidental behavior is broken, not a feature to preserve.

## Two roots

- **App home:** the installation. Code, `sounds/`, the Silero manifest and
  cached models, the base config. One per installation.
- **Workspace:** per-project state. Journal (including per-session files) and
  logs at minimum. Many per installation.

Path resolution contract (target): an absolute path is used as is; a relative
path resolves against the root that owns that setting (app home or workspace),
never against the process cwd.

## Key decisions (owner, 2026-09-26)

- **Workspaces are selected explicitly**, not by the launch cwd. Jarvis is a
  hotkey-driven voice assistant; its start directory reflects a shortcut, not
  the project the user is working on.
- **Memory sharing is a per-workspace choice.** Two equivalent ways, both
  supported:
  - a path in the workspace config (`[memory].root` pointing at a shared
    directory) - the primary, visible mechanism;
  - a directory link (for example an NTFS junction) placed where the workspace
    expects `memory/`. Links are allowed, not forbidden and not required.
  - Links must be **directory** links. A file-level symlink or hardlink to
    `memory.md`/`self.md` silently diverges after the first write, because
    `_atomic_write_text` in `memory/files.py` replaces the file by rename,
    which replaces the link itself rather than its target.
- **Workspace is passed as `--workspace <dir>`** (owner, 2026-09-26). One
  Windows shortcut or `.cmd` per workspace carries the flag. No environment
  variable: it is as invisible as a link and adds a precedence rule for no
  gain; it can be added later without breaking anything if a launch path
  appears that cannot pass a flag. Without the flag the workspace is the app
  home. A missing directory fails start-up with a clear error instead of being
  created silently: a typo in a shortcut must not yield an empty workspace
  with a blank history. Creating a workspace is an explicit action (installer
  command or a dedicated flag; the exact form is task 4's call). No
  "last used workspace" state and no start-up picker in this story.
- **App home is derived, not passed:** it is found from the installed package
  location, so the process cwd plays no role at all.
- **Resolved paths are always visible.** Because Jarvis cannot tell a linked
  directory from a local one, it logs at start-up and shows in the Status
  Console the fully resolved (link-followed) paths of the workspace, journal,
  memory, and logs. This keeps the isolation boundary visible: the user can
  see whether what they say here reaches another workspace's memory.
- **Multiple simultaneous instances are not supported** in the current major
  version. Shared memory between concurrently running workspaces is therefore
  not a supported scenario, and this story does not add locking for it.
- **Installer is a bootstrap script, not packaging.** A wheel entry point or a
  frozen executable (PyInstaller) is out of scope: torch, Silero, and
  pywebview package poorly, and the single-user clone workflow does not need
  it.
- **Installer scope** (owner, 2026-09-26): the reported pain is
  installation, not launching; the installer starts from an existing clone
  or unpacked archive (it does not clone); a missing Python 3.11 is
  installed through winget. Revised the same day: Ollama is a requirement
  the installer checks and stops on, never installs; Ollama models are
  never pulled, only reported as missing.

## Boundaries

- No change to the append-only journal format or its storage layout inside a
  workspace; only where the journal root lives.
- No runtime workspace switching; switching is a restart with another
  workspace.
- No cross-workspace history search or retrieval. A workspace's journal is a
  hard retrieval boundary; that is the point of the feature.
- No multi-instance support and no instance lock (see decisions).
- The installer's network steps (winget for Python, `pip`, `setup_tts_model.py`)
  stay one-time setup. The runtime locality contract in `PROJECT.md` is
  unchanged.
- Installer and workspace behavior touching Ollama, the microphone, TTS
  playback, or the Status Console window are human-run handoffs per the
  Testing protocol; path resolution and config parsing are pure-logic tests.

## Acceptance criteria (draft)

- [ ] One documented bootstrap command, run from a fresh clone in an arbitrary
      directory, produces a runnable installation; re-running it is safe
      (idempotent, never overwrites an existing `config.toml`).
- [ ] Jarvis starts correctly with any process cwd: settings, sound cues, and
      Silero TTS work when launched from outside the app home.
- [ ] A workspace is selected explicitly; journal and logs land under it.
- [ ] Every relative path-valued setting resolves against its owning root;
      absolute paths are unchanged. Covered by config-parsing tests.
- [ ] A workspace can use a shared memory directory either by an absolute
      `[memory].root` or by a directory junction, with no code difference.
- [ ] Start-up log and Status Console show resolved workspace, journal,
      memory, and logs paths; a junctioned memory directory shows its target.
- [ ] Existing single-directory setups keep working without migration: with no
      workspace selected, the default workspace is the app home, so today's
      `journal/`, `logs/`, and `memory/` stay where they are.
- [ ] `PROJECT.md` records the two-root path contract; README "Installation"
      describes the bootstrap command and workspaces.

## Task card sequence

Resequenced 2026-09-26 (owner): the installer goes first because the reported
pain is installation, and it does not depend on the workspace work - until
workspaces land, the installer's launcher starts Jarvis from the app home.

1. **Bootstrap installer.** `task-installer-1-bootstrap-installer.md`.
   Ollama requirement check, Python through winget, venv, dependencies,
   editable package install, config copy, missing-model report, Silero setup,
   launcher; idempotent.
2. **Path inventory and resolution contract.** List every path-valued setting
   and assign it to app home or workspace. Resolve relative paths against the
   owning root. Pure logic, config tests.
3. **App home independence from cwd.** Config discovery relative to the app
   home; the Silero manifest lookup working from any cwd (see open question 4).
4. **Workspace selection and config layering.** `--workspace <dir>` with
   fail-on-missing and an explicit way to create a workspace; default
   workspace equal to the app home; config layering per open question 2;
   the launcher learns to pass `--workspace`.
5. **Resolved-path visibility.** Start-up log lines and a Status Console
   surface for the resolved paths.
6. **Docs and release verification.** README, `PROJECT.md`, human-run
   handoff (fresh clone in a new directory, launch from a foreign cwd, two
   workspaces with shared and local memory).

## Open questions

1. ~~Selection mechanism.~~ Resolved 2026-09-26: `--workspace <dir>` only;
   see Key decisions.
2. **Config layering.** Does a workspace carry its own `config.toml`
   overriding the app-home base config, or only a small workspace file? Where
   does `config.ui.toml` (Status Console-saved state: model, microphone,
   language, VAD) live - app home (device and model choices are per machine)
   or workspace?
3. **Default memory location.** With no memory path configured, is `memory/`
   local to the workspace (share by opting in) or shared in the app home
   (isolate by opting in)? Both are one setting apart; the default decides
   what a new workspace leaks or forgets.
4. **Silero manifest.** The library reads the manifest from the process cwd.
   Options: change cwd to the app home at start-up, or load the model through
   an explicit manifest path if the library allows it. Changing cwd is simple
   but makes every remaining cwd-relative path silently app-home-relative,
   which task 2's inventory must rule out first.
5. **Interaction with the functional self-model (v3.0; was v2.0 until
   2026-09-30).** The self-model is a projection over the journal
   (`roadmap-v1.9-v2.0.md`, v3.0). With per-workspace journals, is
   `self.md` and its reflection substrate per-workspace or global? Decide
   before v3.0 phase 1 fixes its storage.
6. **Relation to sessions.** Sessions already group conversations inside one
   journal (v1.8.1 session files and scope inheritance). The workspace adds a
   hard retrieval boundary on top; confirm that grouping without the boundary
   is not the actual need before implementing.
