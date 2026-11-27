$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot 'wizard_worker.ps1')

try {
    $brand = ConvertTo-DeployBrandParameters $env:JARVIS_WIZARD_BRAND
    if ($env:JARVIS_WIZARD_REBRAND -eq 'True') {
        $check = @{}
        if ($env:JARVIS_WIZARD_CHECK_BRAND -eq 'True') { $check['CheckBrand'] = $true }
        & $env:JARVIS_WIZARD_SCRIPT -Rebrand -Target $env:JARVIS_WIZARD_TARGET -NonInteractive @check @brand
    } elseif ($env:JARVIS_WIZARD_CHECK_BRAND -eq 'True') {
        & $env:JARVIS_WIZARD_SCRIPT -CheckBrand -Mode $env:JARVIS_WIZARD_MODE -NonInteractive @brand
    } else {
        & $env:JARVIS_WIZARD_SCRIPT -Target $env:JARVIS_WIZARD_TARGET `
            -Mode $env:JARVIS_WIZARD_MODE -NonInteractive `
            -Preview:($env:JARVIS_WIZARD_PREVIEW -eq 'True') `
            -Resume:($env:JARVIS_WIZARD_RESUME -eq 'True') `
            -Yes:($env:JARVIS_WIZARD_CONSENT -eq 'True') @brand
    }
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
