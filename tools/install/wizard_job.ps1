$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

try {
    & $env:JARVIS_WIZARD_SCRIPT -Target $env:JARVIS_WIZARD_TARGET `
        -Mode $env:JARVIS_WIZARD_MODE -NonInteractive `
        -Preview:($env:JARVIS_WIZARD_PREVIEW -eq 'True') `
        -Resume:($env:JARVIS_WIZARD_RESUME -eq 'True') `
        -Yes:($env:JARVIS_WIZARD_CONSENT -eq 'True')
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
