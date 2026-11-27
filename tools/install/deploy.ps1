[CmdletBinding(DefaultParameterSetName = 'Deploy')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Deploy')]
    [Parameter(Mandatory = $true, ParameterSetName = 'Rebrand')][string]$Target,
    [ValidateSet('clean', 'copy')][string]$Mode = 'clean',
    [Parameter(ParameterSetName = 'Deploy')][switch]$Resume,
    [Parameter(ParameterSetName = 'Deploy')][switch]$Yes,
    [Parameter(ParameterSetName = 'Deploy')][switch]$Preview,
    [Parameter(Mandatory = $true, ParameterSetName = 'Rebrand')][switch]$Rebrand,
    [Parameter(Mandatory = $true, ParameterSetName = 'CheckBrand')]
    [Parameter(ParameterSetName = 'Rebrand')][switch]$CheckBrand,
    [switch]$NonInteractive,
    [string]$Name,
    [string]$Monogram,
    [string]$Accent,
    [string]$Icon,
    [switch]$NoIcon,
    [switch]$DefaultBrand
)

$ErrorActionPreference = 'Stop'
$assumeYes = $Yes.IsPresent
. (Join-Path $PSScriptRoot 'bootstrap.ps1')

$source = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$targetPath = if ($PSBoundParameters.ContainsKey('Target')) { $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Target) }

# The brand travels in the environment: Windows PowerShell 5.1 drops embedded double quotes from native arguments.
$brand = [ordered]@{}
foreach ($option in 'Name', 'Monogram', 'Accent') {
    if ($PSBoundParameters.ContainsKey($option)) { $brand[$option.ToLowerInvariant()] = [string](Get-Variable -Name $option -ValueOnly) }
}
if ($PSBoundParameters.ContainsKey('Icon')) {
    $brand['icon'] = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Icon)
}
if ($NoIcon) { $brand['no_icon'] = $true }
if ($DefaultBrand) { $brand['default_brand'] = $true }
$brandJson = if ($brand.Count) { $brand | ConvertTo-Json -Compress }
$python = Get-VenvPython $source
if (-not (Test-IsPython311 $python)) {
    # A brand check and a rebrand never start an installation.
    if ($CheckBrand -or $Rebrand -or ($NonInteractive -and -not $assumeYes)) {
        $python = Find-Python311
        if (-not $python) {
            throw 'Python 3.11 was not found. Allow its installation through winget or install Python 3.11 before retrying.'
        }
    } else {
        $python = Get-OrInstallPython311 -AssumeYes $assumeYes
    }
}

$arguments = @('-m', 'tools.deployment', '--source', $source, '--mode', $Mode.ToLowerInvariant())
if ($CheckBrand) {
    $arguments += '--brand-check'
    if ($Rebrand) { $arguments += @('--target', $targetPath) }
} elseif ($Rebrand) {
    $arguments += @('--target', $targetPath, '--rebrand')
} else {
    $arguments += @('--target', $targetPath)
    if ($Resume) { $arguments += '--resume' }
    if ($assumeYes) { $arguments += '--yes' }
    if ($Preview) { $arguments += '--preview' }
}

$previousPythonPath = $env:PYTHONPATH
$previousNonInteractive = $env:JARVIS_DEPLOY_NONINTERACTIVE
$previousBrand = $env:JARVIS_DEPLOY_BRAND
Push-Location -LiteralPath $source
try {
    $env:PYTHONPATH = Join-Path $source 'src'
    $env:JARVIS_DEPLOY_BRAND = $brandJson
    if ($NonInteractive) { $env:JARVIS_DEPLOY_NONINTERACTIVE = '1' }
    & $python @arguments
    $deploymentExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:JARVIS_DEPLOY_NONINTERACTIVE = $previousNonInteractive
    $env:JARVIS_DEPLOY_BRAND = $previousBrand
    Pop-Location
}
exit $deploymentExitCode
