# Story: Jarvis Deployment Wizard

Status: In progress, 2026-11-24. Tasks 1-4 are complete. Documentation and
release verification (task 5) are pending. No release version assigned.

Related work: `story-installer-and-workspaces.md`. Its completed bootstrap
installer is the foundation for this story. Its workspace tasks retain their
existing scope.

## Goal

From a source checkout or an existing Jarvis installation, open a Windows
wizard and deploy a separate, runnable Jarvis into a new directory. The user can
start with an empty history or take a snapshot of the current installation and
continue from it independently.

## User flow

1. **Mode and destination.** Choose Clean installation or Copy current Jarvis,
   then choose a new directory. The wizard shows the source installation and
   rejects an existing destination or a destination inside the source.
2. **Review.** See which settings and data will be transferred, the resolved
   destination paths for journal and memory, and any blocking configuration
   issue. In Copy mode, close the source runtime before taking the snapshot.
3. **Deploy.** See progress through file preparation, snapshot copy when
   applicable, Python environment creation and installation. On failure, see
   the failed stage, the installer output and the available retry action.
4. **Finish.** Open the destination, create a Windows shortcut or launch Jarvis
   from the new home. The launch action becomes available after successful
   installation. Missing optional models appear as setup instructions.

## Mode contract

| Item | Clean installation | Copy current Jarvis |
| --- | --- | --- |
| Application | Same application files and version as the source | Same application files and version as the source |
| Settings | `config.toml` from `config.example.toml` | Own copies of `config.toml`, `config.ui.toml` when present, and supported referenced local files |
| History and memory | Empty at first launch | Full snapshot of the effective journal and memory roots |
| Python environment | New `.venv` installed in the destination | New `.venv` installed in the destination |
| Logs and MCP mode token | Fresh logs and a token generated when MCP mode starts | Fresh logs and a token generated when MCP mode starts |

The journal snapshot includes session records and metadata, media and session
files, transcript and annotation overlays, and the SQLite indexes present in
the source. Memory includes the configured `self.md` and `memory.md` equivalents
and their local backups when present. The effective source settings come from
the same base and UI config layering as Jarvis. Referenced prompt files and other
supported local inputs are copied by value when needed by the new installation.

## Proposed implementation and boundaries

- Use a Windows PowerShell/WPF bootstrap UI that opens before the destination
  has Python dependencies. The wizard and `deploy.cmd -Target <dir> -Mode
  clean|copy` call the same deployment logic. `install.cmd` remains the installer
  for a prepared home and retains its existing behavior.
- Package the application from an explicit file inventory so deployments can
  themselves be used as sources. Install Python dependencies and the editable
  package at the final destination. Reuse the installer's Ollama and model
  checks. Ollama and installed Ollama models stay machine-managed.
- Hold the existing runtime exclusion while reading the snapshot so Jarvis
  cannot change it during copying. Reject a running instance with instructions
  for orderly shutdown. The source configuration and data are read-only inputs.
- Copy configured journal and memory roots by value, including when the source
  roots are absolute. Rebase destination settings so effective journal, memory,
  log and MCP token paths resolve inside the new home. Resolve Windows links
  during validation and reject paths that would keep a write connection to the
  source, including unsupported shared writable stores. Name the blocking key
  or path in the error. Use a path inventory to define which other references
  can be copied, rebased or reported as manual setup before implementation.
- Reserve a new destination before writing. Record when file preparation and
  snapshot copying have completed. Resume installation in a recognized
  incomplete deployment without recopying a completed snapshot. An interrupted
  copy cannot be accepted as a complete snapshot. The retry UX and CLI share
  these rules, and arbitrary existing destinations are rejected.
- Each deployment is one app home using its local state. Runtime workspace
  selection, parallel Jarvis runtimes and changes to journal or memory formats
  remain outside this story. Startup continues to use the existing Windows
  single-instance guard and runtime locality contract.

## Acceptance criteria

- [ ] The wizard opens without a destination `.venv`, and both deployment modes
  produce a runnable Jarvis home from both supported source types.
- [ ] Clean mode creates default settings and an empty journal and memory,
  even when the source contains settings and history.
- [ ] Copy mode preserves session IDs, journal records, attachments, overlays
  and memory at the snapshot boundary. The copied home uses its own storage
  even when the source configured absolute paths or a linked root.
- [ ] After submitting a message and editing memory in the copy, the test
  message and edit appear there, and the original journal and memory still
  match their pre-run file inventories and hashes.
- [ ] Deployment rejects a running source in Copy mode, existing destinations,
  and paths that would cause supported writes to reach the source. Failure
  messages explain the blocking condition before the installer runs.
- [ ] A failed installation can be resumed from its completed snapshot.
  Interruption during snapshot copying and retries against unrelated directories
  are covered by automated tests.
- [ ] Both entry points use the same mode and validation rules. Automated tests
  cover path planning, snapshot isolation and resume with a fake installer. The
  human-run handoff verifies the wizard, shortcut and real launch on Windows.

## Ordered task-card sequence

1. **Deployment inventory and plan validation.** Define the supported source
   layout, app file inventory and per-setting path handling. Test effective
   paths, overlap, existing destinations and Windows links using fixtures.
2. **Clean deployment and installer reuse.** Implement the shared deployment
   command and manifest, final-path installation and safe retry. Verify it
   with a fake installer and exercise both source layouts.
3. **Copy deployment and isolation.** Add runtime exclusion, full snapshot
   copying, config rebasing and destination path verification. Test interrupted
   snapshots and copying from absolute or linked roots.
4. **Windows wizard.** Build and wire the four screens, progress and retry,
   plus final launch and shortcut actions. Test the UI state transitions and
   prepare a Windows visual review handoff.
5. **Documentation and release verification.** Document both entry points and
   the path contract. Prepare an end-to-end human handoff that demonstrates
   clean deployment, history preservation, and isolation using the journal and
   memory hash comparison above. Record any architecture decisions in
   `PROJECT.md` when they land.
