# Task: Deployment Wizard 2 - clean deployment and installer reuse

Status: Completed. Automated checks passed 2026-11-24. Real Windows
installation and launch are covered by the human-run handoff below.
Story: `story-deployment-wizard.md`, task 2.
Predecessor: `task-deployment-wizard-1-plan-validation.md`.

## Boundary

Provide `deploy.cmd -Target <directory> -Mode clean` for a checkout or a
deployed home. Reuse the read-only plan and the existing bootstrap installer.
Copy mode and GUI integration remain tasks 3 and 4.

The command prefers the source `.venv` and can bootstrap Python 3.11 through
the same discovery and consent flow as `install.cmd`. Both interpreter paths
use the source `src/` for planning. The destination installer runs with the
destination as its working directory and prepares its own Python environment.

## Acceptance criteria

- Transfer only the application inventory into an exclusively reserved new
  directory. Keep an on-disk deployment manifest that records preparation,
  readiness for installation, and completion.
- Invoke the installer at the final path and report its exit status. Omit
  source settings, history, venv and unrelated files.
- `-Resume` can retry a failed installer on a prepared target without reading
  or copying the source. Reject incomplete file preparation, completed targets,
  moved manifests and unrecognized destinations. Keep the existing installer
  recovery instructions for an unusable destination `.venv`.
- Serialize deployment attempts for the same destination. Test both source
  layouts and the failure and retry paths with a fake installer. Prepare a
  Windows handoff for real dependency installation and launching Jarvis.

## Windows handoff

Docs debt: `deploy.cmd` is not yet documented in `README.md` or `README.ru.md`.
Story task 5 adds those instructions. Use this handoff for the current check.

From the source home, choose a new destination. The example below checks for
an existing path before deploying. The installer requires the Ollama executable
and can offer to install Python 3.11 (`bootstrap.ps1`). Allow dependency setup
and follow any missing-model instructions printed by `installer.py` before
launching.

```powershell
$destination = Join-Path (Split-Path -Parent (Get-Location).Path) 'Jarvis-clean-check'
if (Test-Path -LiteralPath $destination) { throw "Choose a new destination: $destination" }
.\deploy.cmd -Target $destination -Mode clean
if ($LASTEXITCODE -ne 0) { throw "Deployment failed with exit code $LASTEXITCODE" }
Get-Content -Raw -Encoding UTF8 (Join-Path $destination '.jarvis-deployment.json')
```

Confirm the manifest phase is `complete`, the destination `.venv` and
`config.toml` exist, and the source's `config.ui.toml`, history and memory
were excluded. For the launch check, read `[backend].endpoint` from the
destination `config.toml`. It defaults to `http://localhost:11434` in
`config.example.toml`, which `installer.py` copies for clean deployments.
Open Ollama if it is not running and verify the configured endpoint responds
at `/api/tags` (`installer.py` uses the same endpoint for the model check).
For the default, use `Invoke-RestMethod http://localhost:11434/api/tags`.
Close any running Jarvis, then launch the destination
with `& (Join-Path $destination 'Jarvis.cmd')`. In the Status Console verify the
Journal has no sessions from the source. `Jarvis.cmd` selects the destination
directory and enables `--status-console`. Default journal and memory roots
in `config.example.toml` are `journal` and `memory`.

If installation reported an error after file preparation, address the cause
shown in its output, then run `.\deploy.cmd -Target $destination -Mode clean
-Resume` from the source home as one command. Verify preparation is skipped
and the manifest reaches `complete`.
