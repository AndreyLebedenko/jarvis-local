# Deployment Wizard release handoff

Run this procedure on Windows 11 from an installed test source on the branch
under review. Run all PowerShell blocks in the same window. Use a test home
whose Journal and Memory you can edit. Leave the two destinations available
for review after the run.

## Prepare the test source

Close any running Jarvis. In the test source, use these effective settings.
`config.py` loads `config.toml` and applies `config.ui.toml` on top. Change the
layer that sets a different value, or add the key to the base layer if needed.
These values are the defaults in `config.example.toml`.

| Key | Value for this run | Purpose |
| --- | --- | --- |
| `[journal].enabled` | `true` | Record the source and copy turns. |
| `[mcp].enabled` | `false` | Allow Copy without an enabled tool provider. |
| `[ui].language` | `"en"` | Match the Status Console control names below. |
| `[response].mode` | `"text"` | Use the text response path. |

Install Ollama and start it. `bootstrap.ps1` checks for the executable.
`[backend].endpoint` defaults to `http://localhost:11434` and `[backend].model`
defaults to `gemma4:12b` in `config.example.toml`. The test source may have
different values. The following probe uses the settings Jarvis actually reads.
Ensure the configured model is listed by `/api/tags`, the endpoint used by
`installer.py`. If a model is missing, follow the installer output and run
`ollama pull <model>` against the configured server before launching. See the
installation section in `README.md` for `OLLAMA_HOST` when using a nondefault
endpoint.

```powershell
$ErrorActionPreference = 'Stop'
$source = (Get-Location).Path
$suffix = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$parent = Split-Path -Parent $source
$clean = Join-Path $parent "Jarvis-clean-$suffix"
$copy = Join-Path $parent "Jarvis-copy-$suffix"
$sourceMarker = "Deployment source $suffix"
$copyMarker = "Deployment copy $suffix"
foreach ($target in @($clean, $copy)) {
    if (Test-Path -LiteralPath $target) { throw "Choose a new target: $target" }
}

$settingsProbe = @'
import json
from pathlib import Path
from jarvis.core.config import load_settings
s = load_settings()
print(json.dumps(dict(journal=str(Path(s.journal.root).resolve()),
    memory=str(Path(s.memory.root).resolve()), memory_file=s.memory.memory_file,
    journal_enabled=s.journal.enabled, mcp_enabled=s.mcp.enabled,
    language=s.ui.language, response_mode=s.response.mode,
    endpoint=s.backend.endpoint, model=s.backend.model)))
'@

function Get-ReleaseSettings([string]$HomePath) {
    Push-Location -LiteralPath $HomePath
    try {
        $data = & .\.venv\Scripts\python.exe -c $settingsProbe
        if ($LASTEXITCODE -ne 0) { throw "Could not read settings: $HomePath" }
        $data | ConvertFrom-Json
    } finally {
        Pop-Location
    }
}

$sourceSettings = Get-ReleaseSettings $source
if (-not $sourceSettings.journal_enabled -or $sourceSettings.mcp_enabled -or
    $sourceSettings.language -ne 'en' -or $sourceSettings.response_mode -ne 'text') {
    throw 'Set the four effective source settings in the table above and retry.'
}
$sourceAndCleanEndpoints = @($sourceSettings.endpoint.TrimEnd('/'), 'http://localhost:11434')
foreach ($endpoint in ($sourceAndCleanEndpoints | Select-Object -Unique)) {
    $models = Invoke-RestMethod -Uri "$endpoint/api/tags"
    "$endpoint model tags: $($models.models.name -join ', ')"
}
"Source marker: $sourceMarker"
"Copy marker:   $copyMarker"
"Clean target:  $clean"
"Copy target:   $copy"
```

Run `& (Join-Path $source 'Jarvis.cmd')`. `Jarvis.cmd` starts `--status-console`
in its own home. Use the **Journal** tab and switch **Hidden** to **Open** if
needed using the Open/Hidden control documented in `README.md`. Enter the
printed source marker into the text input and click **Send**. Open **Memory**,
add the same marker on its own line in `memory.md`, and click **Save**.
`[memory].memory_file` defaults to `memory.md` in `config.example.toml`.
The editor button and labels are in `strings.js`. Wait for the response and
save to complete, then use **Shut down** and confirm **Shut down** in the
Status Console. The command should return to PowerShell.

Record the source journal and memory. The paths below come from
`[journal].root` and `[memory].root`, which default to `journal` and `memory`
in `config.example.toml`. The function records the relative filename and SHA-256
of every file, including hidden files.

```powershell
function Get-ReleaseInventory($Settings) {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($role in @('journal', 'memory')) {
            $root = $Settings.$role
            if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
            Get-ChildItem -LiteralPath $root -File -Recurse -Force | ForEach-Object {
                $relative = $_.FullName.Substring($root.Length).TrimStart([char[]]@('\', '/'))
                $stream = [IO.File]::OpenRead($_.FullName)
                try {
                    $hash = [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '')
                    '{0}/{1} {2}' -f $role, $relative, $hash
                } finally {
                    $stream.Dispose()
                }
            }
        }
    } finally {
        $sha256.Dispose()
    }
}

function Find-ReleaseJournalMarker($Settings, [string]$Marker) {
    Get-ChildItem -LiteralPath $Settings.journal -File -Recurse -Filter 'events.jsonl' |
        Select-String -Pattern $Marker -SimpleMatch
}

$sourceBefore = @(Get-ReleaseInventory $sourceSettings | Sort-Object)
$sourceMemory = Join-Path $sourceSettings.memory $sourceSettings.memory_file
if (-not (Find-ReleaseJournalMarker $sourceSettings $sourceMarker) -or
    -not (Select-String -LiteralPath $sourceMemory -Pattern $sourceMarker -SimpleMatch)) {
    throw 'The source Journal and saved Memory marker are required.'
}
```

## Run A - Clean in the wizard

1. Run `.\DeploymentWizard.cmd` in the test source. Select **Clean
   installation** and paste the printed `$clean` path into **Destination
   folder**. Select **Review**. Confirm that the displayed journal and memory
   paths are inside `$clean`. Select **Deploy**. The installer output should
   appear while the window remains responsive.
2. On **Jarvis is ready**, use **Open folder** and verify Explorer opens
   `$clean`. Use **Create shortcut...** to save one shortcut. Its Windows
   properties should target `$clean\Jarvis.cmd` and use `$clean` as **Start in**
   (`wizard.ps1`).
3. Select **Launch Jarvis**. In **Journal**, switch to **Open** if needed and
   confirm there are no sessions. In **Memory**, confirm the source marker is
   absent. Shut down the Clean instance, then close the wizard.

## Run B - Copy from the CLI

Keep the source and Clean runtimes closed. From the source home run:

```powershell
.\deploy.cmd -Target $copy -Mode copy
if ($LASTEXITCODE -ne 0) { throw "Copy deployment failed with code $LASTEXITCODE" }
```

If the installer fails after preparation, address the reported cause and run
`.\deploy.cmd -Target $copy -Mode copy -Resume`. `deployment.py` accepts this
only for phase `ready`. If the phase is `preparing`, choose a new destination,
set `$copy` to its path, and run Copy again. After a successful deployment run
the next block before starting the copy.

```powershell
$marker = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $copy '.jarvis-deployment.json') | ConvertFrom-Json
if ($marker.mode -ne 'copy' -or $marker.phase -ne 'complete') {
    throw 'Copy deployment did not complete'
}
$copySettings = Get-ReleaseSettings $copy
if ($copySettings.journal -ne (Join-Path $copy 'journal') -or
    $copySettings.memory -ne (Join-Path $copy 'memory')) {
    throw 'Copy storage paths do not match the new home'
}
$copyBefore = @(Get-ReleaseInventory $copySettings | Sort-Object)
if ($sourceBefore.Count -ne $copyBefore.Count -or (Compare-Object $sourceBefore $copyBefore)) {
    throw 'The copy journal or memory differs from the source snapshot'
}
"Copy matches the source snapshot: $($copyBefore.Count) files"
```

Run `& (Join-Path $copy 'Jarvis.cmd')`. In **Journal**, confirm the source
marker is present in its old session. Enter the printed copy marker and click
**Send**. In **Memory**, confirm the source marker was copied, add the copy
marker on a new line, and click **Save**. Wait for the response and save, then
shut down the Copy instance. Run the final check:

```powershell
$sourceAfter = @(Get-ReleaseInventory $sourceSettings | Sort-Object)
if ($sourceBefore.Count -ne $sourceAfter.Count -or (Compare-Object $sourceBefore $sourceAfter)) {
    throw 'Source Journal or memory changed after writes in the copy'
}
$copyMemory = Join-Path $copySettings.memory $copySettings.memory_file
if (-not (Select-String -LiteralPath $copyMemory -Pattern $copyMarker -SimpleMatch)) {
    throw 'Copy memory write was not saved'
}
if (-not (Find-ReleaseJournalMarker $copySettings $copyMarker)) {
    throw 'Copy Journal write was not recorded'
}
"PASS: $($sourceAfter.Count) source files are unchanged. Copy Journal and Memory both recorded the new marker."
```

The raw Journal filename `events.jsonl` is defined in `store.py`.

## Record the results

- Windows version and branch commit:
- Clean wizard, empty Journal and shortcut target:
- Copy CLI, original session visible and pre-launch snapshot file count:
- Final `PASS` line or failure details:
- Installer resume result, if used:
