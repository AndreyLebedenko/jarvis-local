$ErrorActionPreference = 'Stop'

function Show-WizardStartupError {
    param([string]$Message)

    $title = 'Jarvis Deployment Wizard'
    $details = "The wizard could not open.`r`n`r`n$Message"
    [Console]::Error.WriteLine($details)
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show($details, $title, 'OK', 'Error')
    } catch {
        $shell = New-Object -ComObject WScript.Shell
        [void]$shell.Popup($details, 0, $title, 16)
    }
}

function Invoke-WizardStartup {
    param([scriptblock]$Open, [scriptblock]$ReportError)

    try {
        & $Open | Out-Host
        return 0
    } catch {
        & $ReportError $_.Exception.Message | Out-Host
        return 1
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $exitCode = Invoke-WizardStartup { & (Join-Path $PSScriptRoot 'wizard.ps1') } `
        { param($message) Show-WizardStartupError $message }
    exit $exitCode
}
