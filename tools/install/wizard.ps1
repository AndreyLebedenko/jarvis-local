$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, System.Windows.Forms
. (Join-Path $PSScriptRoot 'wizard_worker.ps1')

$source = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$backend = Join-Path $PSScriptRoot 'deploy.ps1'
$xaml = [xml](Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'wizard.xaml'))
$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)
$controls = @{}
foreach ($name in @(
    'PageTitle', 'PageStatus', 'ChoicePane', 'SourceText', 'CleanMode', 'CopyMode',
    'TargetText', 'BrowseButton', 'PythonConsent', 'ReviewPane', 'OutputPane',
    'ProgressBar', 'OutputText', 'FinishActions', 'OpenButton', 'ShortcutButton',
    'LaunchButton', 'BackButton', 'NextButton', 'CloseButton'
)) {
    $controls[$name] = $window.FindName($name)
}
$controls.SourceText.Text = $source
$controls.TargetText.Text = "$source-new"
$script:worker = $null
$script:request = $null
$script:previewResult = $null
$script:deploymentResult = $null
$script:page = ''

function Show-WizardPage {
    param([string]$Page, [string]$Message = '')

    $script:page = $Page
    $controls.ChoicePane.Visibility = if ($Page -eq 'choice') { 'Visible' } else { 'Collapsed' }
    $controls.ReviewPane.Visibility = if ($Page -eq 'review') { 'Visible' } else { 'Collapsed' }
    $controls.OutputPane.Visibility = if ($Page -in @('choice', 'review')) { 'Collapsed' } else { 'Visible' }
    $controls.ProgressBar.Visibility = if ($Page -eq 'busy') { 'Visible' } else { 'Collapsed' }
    $controls.FinishActions.Visibility = if ($Page -eq 'finish') { 'Visible' } else { 'Collapsed' }
    $controls.BackButton.IsEnabled = $Page -in @('review', 'retry', 'error')
    $controls.BackButton.Visibility = if ($controls.BackButton.IsEnabled) { 'Visible' } else { 'Collapsed' }
    $controls.CloseButton.IsEnabled = $Page -ne 'busy'
    $controls.NextButton.IsEnabled = $Page -in @('choice', 'review', 'retry')
    $controls.NextButton.Visibility = if ($controls.NextButton.IsEnabled) { 'Visible' } else { 'Collapsed' }
    $controls.NextButton.Content = switch ($Page) {
        'choice' { 'Review' }
        'review' { if ($script:request.Resume) { 'Resume installation' } else { 'Deploy' } }
        'retry' { 'Resume installation' }
        default { 'Continue' }
    }
    $controls.PageTitle.Text = switch ($Page) {
        'choice' { 'Deploy Jarvis' }
        'review' { 'Review deployment' }
        'busy' { if ($script:request.Preview) { 'Checking deployment' } else { 'Deploying Jarvis' } }
        'retry' { 'Installation needs attention' }
        'error' { 'Deployment could not continue' }
        'finish' { 'Jarvis is ready' }
    }
    $controls.PageStatus.Text = $Message
}

function Start-WizardStep {
    param([bool]$Preview)

    $script:request.Preview = $Preview
    $script:previewResult = $null
    $script:deploymentResult = $null
    $controls.OutputText.Clear()
    try {
        $script:worker = Start-DeploymentWorker -ScriptPath $backend `
            -Target $script:request.Target -Mode $script:request.Mode -Preview $Preview `
            -Resume $script:request.Resume -Consent $script:request.Consent
        Show-WizardPage 'busy' 'The output below shows each step as it runs.'
    } catch {
        $controls.OutputText.Text = $_.Exception.Message
        Show-WizardPage 'error' 'Go back to review your selection.'
    }
}

function Set-WizardReview {
    $preview = $script:previewResult
    $script:request.Target = $preview.target
    if ($script:request.Resume) {
        $summary = @('Resume installation from the prepared files.', '', "Destination: $($preview.target)")
    } else {
        $summary = @("Source: $($preview.source)", "Destination: $($preview.target)", '')
        if ($preview.mode -eq 'copy') {
            $settingsFiles = @($preview.settings)
            if ('config.toml' -notin $settingsFiles) {
                $settingsFiles = @('Installer defaults') + $settingsFiles
            }
            $settings = $settingsFiles -join ', '
            $summary += @(
                "Settings: $settings",
                "Journal snapshot: $($preview.source_journal)",
                "Memory snapshot: $($preview.source_memory)",
                'Referenced prompts and supported local assets are included.'
            )
        } else {
            $summary += 'Default settings, empty journal and empty memory.'
        }
        $summary += @('', "New journal: $($preview.journal)", "New memory: $($preview.memory)")
    }
    $controls.ReviewPane.Text = $summary -join [Environment]::NewLine
    Show-WizardPage 'review'
}

function Complete-WizardStep {
    param([int]$ExitCode)

    $script:worker.Process.Dispose()
    $script:worker = $null
    $preview = $script:request.Preview
    $success = $ExitCode -eq 0 -and (-not $preview -or $null -ne $script:previewResult)
    $phase = if (-not $success -and -not $preview) {
        Get-DeploymentWizardPhase -Target $script:request.Target -Mode $script:request.Mode
    }
    $canRetry = $phase -eq 'ready'
    switch (Get-DeploymentWizardOutcome -Preview $preview -Succeeded $success -CanRetry $canRetry) {
        'review' { Set-WizardReview }
        'finish' { Show-WizardPage 'finish' $script:request.Target }
        'retry' {
            $script:request.Resume = $true
            Show-WizardPage 'retry' 'Address the installer error below, then resume installation.'
        }
        'error' {
            if ($ExitCode -eq 0) {
                $controls.OutputText.AppendText("The deployment planner returned no review data.`r`n")
            }
            $guidance = if ($phase -eq 'preparing') {
                Get-DeploymentPreparationHint -Target $script:request.Target
            } else {
                'Read the details below. Go back to change your selection.'
            }
            Show-WizardPage 'error' $guidance
        }
    }
}

$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(100)
$timer.Add_Tick({
    if ($null -eq $script:worker) { return }
    try {
        $batch = Receive-DeploymentWorker $script:worker
        foreach ($line in $batch.Lines) {
            $prefix = 'JARVIS_DEPLOY_PREVIEW:'
            if ($script:request.Preview -and $line.StartsWith($prefix)) {
                $script:previewResult = $line.Substring($prefix.Length) | ConvertFrom-Json
            } elseif ($result = ConvertFrom-DeploymentResultLine $line) {
                $script:deploymentResult = $result
            } else {
                $controls.OutputText.AppendText($line + [Environment]::NewLine)
            }
        }
        if ($batch.Lines.Count) { $controls.OutputText.ScrollToEnd() }
        if ($batch.Done) { Complete-WizardStep $batch.ExitCode }
    } catch {
        $controls.OutputText.AppendText($_.Exception.Message + [Environment]::NewLine)
        if ($script:worker -and $script:worker.Process.HasExited) { Complete-WizardStep 1 }
    }
})

$controls.BrowseButton.Add_Click({
    $picker = New-Object Windows.Forms.FolderBrowserDialog
    try {
        $picker.Description = 'Choose the parent folder for the new Jarvis directory.'
        if ($picker.ShowDialog() -eq 'OK') {
            $leaf = if ($controls.CopyMode.IsChecked) { 'Jarvis-copy' } else { 'Jarvis-clean' }
            $controls.TargetText.Text = Join-Path $picker.SelectedPath $leaf
        }
    } finally {
        $picker.Dispose()
    }
})
$controls.NextButton.Add_Click({
    if ($script:page -eq 'choice') {
        $value = $controls.TargetText.Text.Trim()
        try {
            if ([string]::IsNullOrWhiteSpace($value)) { throw 'Choose a destination folder.' }
            $target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($value)
            $mode = if ($controls.CopyMode.IsChecked) { 'copy' } else { 'clean' }
            $phase = Get-DeploymentWizardPhase -Target $target -Mode $mode
            if ($phase -eq 'preparing') {
                $controls.PageStatus.Text = Get-DeploymentPreparationHint -Target $target
                return
            }
            $script:request = [pscustomobject]@{
                Target = $target
                Mode = $mode
                Resume = ($phase -eq 'ready')
                Consent = [bool]$controls.PythonConsent.IsChecked
                Preview = $true
            }
            Start-WizardStep $true
        } catch {
            $controls.PageStatus.Text = $_.Exception.Message
        }
    } elseif ($script:page -in @('review', 'retry')) {
        Start-WizardStep $false
    }
})
$controls.BackButton.Add_Click({ Show-WizardPage 'choice' })
$controls.CloseButton.Add_Click({ $window.Close() })
$window.Add_Closing({
    param($sender, $eventArgs)
    if ($script:worker) {
        $eventArgs.Cancel = $true
        $controls.PageStatus.Text = 'Wait for the current step to finish before closing.'
    }
})
$controls.OpenButton.Add_Click({
    try { Invoke-Item -LiteralPath $script:request.Target } catch { $controls.PageStatus.Text = $_.Exception.Message }
})
$controls.LaunchButton.Add_Click({
    try {
        Start-Process -FilePath (Join-Path $script:request.Target 'Jarvis.cmd') `
            -WorkingDirectory $script:request.Target -WindowStyle Hidden
    } catch { $controls.PageStatus.Text = $_.Exception.Message }
})
$controls.ShortcutButton.Add_Click({
    try {
        $save = New-Object Microsoft.Win32.SaveFileDialog
        $save.Title = 'Save Jarvis shortcut'
        $save.InitialDirectory = [Environment]::GetFolderPath('Desktop')
        $save.FileName = if ($script:deploymentResult) {
            $script:deploymentResult.shortcut_file
        } else {
            'Jarvis - ' + (Split-Path -Leaf $script:request.Target) + '.lnk'
        }
        $save.Filter = 'Windows shortcut (*.lnk)|*.lnk'
        $save.DefaultExt = '.lnk'
        if ($save.ShowDialog($window)) {
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($save.FileName)
            $shortcut.TargetPath = Join-Path $script:request.Target 'Jarvis.cmd'
            $shortcut.WorkingDirectory = $script:request.Target
            $icon = if ($script:deploymentResult) {
                $script:deploymentResult.shortcut_icon
            } else {
                Join-Path $script:request.Target 'src\jarvis\launcher\assets\jarvis.ico'
            }
            $shortcut.IconLocation = $icon + ',0'
            $shortcut.Save()
            $controls.PageStatus.Text = "Saved shortcut: $($save.FileName)"
        }
    } catch { $controls.PageStatus.Text = $_.Exception.Message }
})

Show-WizardPage 'choice'
$timer.Start()
try { [void]$window.ShowDialog() } finally { $timer.Stop() }
