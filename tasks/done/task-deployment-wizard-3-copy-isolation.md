# Task: Deployment Wizard 3 - copy deployment and isolation

Status: Completed. Automated checks passed 2026-11-24. The Windows handoff
below covers real installation and runtime isolation.
Story: `story-deployment-wizard.md`, task 3.
Predecessor: `task-deployment-wizard-2-clean-install.md`.

## Boundary

Enable `deploy.cmd -Target <directory> -Mode copy`. Hold the Jarvis runtime
mutex while planning and copying source state. Copy both configuration layers
and rebase known path settings in each layer. Preserve formatting and comments
with the approved standard-library patcher. Reject path values the patcher
cannot safely edit and identify the key. Parse the result and compare the
tables before loading and validating the destination's effective settings.

- Copy journal and memory trees by value, including roots given as absolute
  paths or junctions. Reject nested links instead of following them across
  the snapshot boundary. Create fresh log, token and Piper download locations.
- Copy referenced prompts, Personal Proxy files, cues and Piper read assets by
  value. Preserve both layers so a later UI settings save cannot revive a
  source path. A missing local proxy file stays missing in the copy. Shared
  Piper model paths produce one asset and keep the normal local model layout.
  Retain the active MCP tool-provider rejection from task 1.
- When the source has no `config.toml`, validate the installer example against
  the destination path contract and let the installer create the base layer.
- Record `ready` only after the snapshot and its validation complete. Retain
  task 2's installer retry behavior. GUI and user documentation remain in
  tasks 4 and 5.

## Acceptance criteria

- Copy preserves snapshot bytes, source configuration bytes, and unrelated
  settings and comments in the destination configuration. A destination-only
  journal or memory write leaves source files unchanged.
- Refuse a running runtime, unsafe nested links and unsupported TOML forms.
  An interruption leaves the manifest in `preparing` and skips installation.
- Both base and UI paths are local after rebasing. Validate the copy again
  before resuming a failed installer.
- Verify with filesystem fixtures and the existing fake installer. Prepare a
  human handoff for real Windows deployment and launching the two homes.

## Windows handoff

`deploy.cmd` remains undocumented in the READMEs until story task 5. Use this
handoff from an installed source with at least one recorded Journal turn. Close
every running Jarvis before copying. Use a test source whose effective
`[mcp].enabled` is `false` in the base and UI config layers. Its default is
`false` in `config.example.toml`. For the install and launch prerequisites,
follow the Ollama steps in `task-deployment-wizard-2-clean-install.md`. The copy
preserves `[backend].endpoint` from `config.toml` and `config.ui.toml`. The
default is `http://localhost:11434` in `config.example.toml`; check the
configured endpoint with `/api/tags` as in `installer.py` before launching.

Run the following in PowerShell from the source home. It reads the effective
`[journal].root` and `[memory].root` with `load_settings()` from `config.py`
and hashes all files under them. The default directory names are `journal`
and `memory` in `config.example.toml`.

```powershell
$source = (Get-Location).Path
$destination = Join-Path (Split-Path -Parent $source) 'Jarvis-copy-check'
if (Test-Path -LiteralPath $destination) { throw "Choose a new destination: $destination" }
$rootsJson = & .\.venv\Scripts\python.exe -c 'import json; from pathlib import Path; from jarvis.core.config import load_settings; s=load_settings(); print(json.dumps([str(Path(s.journal.root).resolve()), str(Path(s.memory.root).resolve())]))'
if ($LASTEXITCODE -ne 0) { throw 'Could not load source settings' }
$roots = $rootsJson | ConvertFrom-Json
function Get-SnapshotHashes {
    foreach ($root in $roots) {
        if (Test-Path -LiteralPath $root) {
            Get-ChildItem -LiteralPath $root -File -Recurse -Force |
                Get-FileHash -Algorithm SHA256 | Sort-Object Path |
                ForEach-Object { "{0} {1}" -f $_.Hash, $_.Path }
        }
    }
}
$before = @(Get-SnapshotHashes)
.\deploy.cmd -Target $destination -Mode copy
if ($LASTEXITCODE -ne 0) { throw "Copy failed with exit code $LASTEXITCODE" }
Get-Content -Raw -Encoding UTF8 (Join-Path $destination '.jarvis-deployment.json')
```

Confirm the manifest reports mode `copy` and phase `complete`. If the copy has
`[journal].enabled` set to `false` in either config layer, set it to `true` in
that layer in the copy. Its default is `true` in `config.example.toml`. Launch
the copy with `& (Join-Path $destination 'Jarvis.cmd')`. That launcher starts
the Status Console. If it shows **Hidden**, switch to **Open** using its
Open/Hidden control (`README.md`). In the **Journal** tab, confirm the old
session is visible and submit `Copy isolation check 20261124` through its text
input. Edit the file named by `[memory].memory_file` in the curated memory
controls. It defaults to `memory.md` in `config.example.toml`. The Journal
input and memory controls are listed under the Status Console tabs in
`README.md`. Confirm the new message and memory edit are visible in the copy.
Close the copy before comparing:

```powershell
$after = @(Get-SnapshotHashes)
if ($before.Count -ne $after.Count -or
    ($before.Count -gt 0 -and (Compare-Object $before $after))) {
    throw 'Source history or memory changed'
}
```

If only the installer failed, use `-Mode copy -Resume` with the same target
after addressing the reported cause. `deployment.py` binds resume to the
stored mode and allows it only after the snapshot reached `ready`.
