$script:DeploymentWorkerJob = Join-Path $PSScriptRoot 'wizard_job.ps1'

function Start-DeploymentWorker {
    param(
        [string]$ScriptPath, [string]$Target, [string]$Mode,
        [bool]$Preview, [bool]$Resume, [bool]$Consent
    )

    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = Join-Path $PSHOME 'powershell.exe'
    $info.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $script:DeploymentWorkerJob
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.RedirectStandardInput = $true
    $info.StandardOutputEncoding = [Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    $info.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $info.EnvironmentVariables['JARVIS_WIZARD_SCRIPT'] = $ScriptPath
    $info.EnvironmentVariables['JARVIS_WIZARD_TARGET'] = $Target
    $info.EnvironmentVariables['JARVIS_WIZARD_MODE'] = $Mode
    $info.EnvironmentVariables['JARVIS_WIZARD_PREVIEW'] = [string]$Preview
    $info.EnvironmentVariables['JARVIS_WIZARD_RESUME'] = [string]$Resume
    $info.EnvironmentVariables['JARVIS_WIZARD_CONSENT'] = [string]$Consent

    $process = [Diagnostics.Process]::Start($info)
    $process.StandardInput.Close()
    return [pscustomobject]@{
        Process = $process
        Streams = @(
            @{ Reader = $process.StandardOutput; Pending = $process.StandardOutput.ReadLineAsync() }
            @{ Reader = $process.StandardError; Pending = $process.StandardError.ReadLineAsync() }
        )
    }
}

function Receive-DeploymentWorker {
    param($Worker)

    $lines = New-Object 'Collections.Generic.List[string]'
    foreach ($stream in $Worker.Streams) {
        for ($count = 0; $count -lt 100 -and $stream.Pending -and $stream.Pending.IsCompleted; $count++) {
            $line = $stream.Pending.GetAwaiter().GetResult()
            if ($null -eq $line) {
                $stream.Pending = $null
                break
            }
            $lines.Add($line)
            $stream.Pending = $stream.Reader.ReadLineAsync()
        }
    }
    $done = $Worker.Process.HasExited -and -not ($Worker.Streams | Where-Object { $_.Pending })
    $exitCode = if ($done) { $Worker.Process.ExitCode }
    return [pscustomobject]@{ Lines = $lines; Done = $done; ExitCode = $exitCode }
}

function Get-DeploymentWizardPhase {
    param([string]$Target, [string]$Mode)

    $marker = Join-Path $Target '.jarvis-deployment.json'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return }
    try {
        $record = Get-Content -Raw -LiteralPath $marker -Encoding UTF8 | ConvertFrom-Json
        $path = [IO.Path]::GetFullPath($Target).TrimEnd([char[]]@('\', '/'))
        if ($record.schema -ne 1 -or $record.target -ne $path -or $record.mode -notin @('clean', 'copy')) { return }
        if ($record.phase -eq 'preparing') { return 'preparing' }
        if ($record.phase -eq 'ready' -and $record.mode -eq $Mode) { return 'ready' }
    } catch {
        return
    }
}

function Get-DeploymentPreparationHint {
    param([string]$Target)

    return "File preparation is incomplete: $Target. Remove the incomplete directory and start again, or choose a new destination."
}

function Get-DeploymentWizardOutcome {
    param([bool]$Preview, [bool]$Succeeded, [bool]$CanRetry)

    if ($Succeeded) {
        if ($Preview) { return 'review' }
        return 'finish'
    }
    if (-not $Preview -and $CanRetry) { return 'retry' }
    return 'error'
}
