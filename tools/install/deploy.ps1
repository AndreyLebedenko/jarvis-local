param(
    [Parameter(Mandatory = $true)][string]$Target,
    [ValidateSet('clean', 'copy')][string]$Mode = 'clean',
    [switch]$Resume,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$assumeYes = $Yes.IsPresent
. (Join-Path $PSScriptRoot 'bootstrap.ps1')

$source = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$targetPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Target)
$python = Get-VenvPython $source
if (-not (Test-IsPython311 $python)) {
    $python = Get-OrInstallPython311 -AssumeYes $assumeYes
}

$arguments = @('-m', 'tools.deployment', '--source', $source, '--target', $targetPath, '--mode', $Mode.ToLowerInvariant())
if ($Resume) { $arguments += '--resume' }
if ($assumeYes) { $arguments += '--yes' }

$previousPythonPath = $env:PYTHONPATH
Push-Location -LiteralPath $source
try {
    $env:PYTHONPATH = Join-Path $source 'src'
    & $python @arguments
    $deploymentExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
exit $deploymentExitCode
