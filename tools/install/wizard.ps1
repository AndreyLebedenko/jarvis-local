$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, System.Windows.Forms
. (Join-Path $PSScriptRoot 'wizard_worker.ps1')
. (Join-Path $PSScriptRoot 'wizard_pages.ps1')
. (Join-Path $PSScriptRoot 'wizard_identity.ps1')
. (Join-Path $PSScriptRoot 'wizard_preview.ps1')

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
    'LaunchButton', 'BackButton', 'NextButton', 'CloseButton', 'CustomizeButton',
    'IdentitySummary', 'IdentityPane', 'IdentityStatus', 'IdentityName', 'IdentityNameMessage',
    'IdentityMonogram', 'IdentityMonogramHint', 'IdentityMonogramMessage', 'AccentSwatch',
    'IdentityAccent', 'PickColourButton', 'IdentityAccentMessage', 'IdentityIconText',
    'ChoosePngButton', 'RemovePngButton', 'IdentityIconMessage', 'RestoreDefaultButton',
    'DiscardButton', 'IdentityGeneralMessage', 'PreviewLarge', 'PreviewCaption',
    'PreviewDark32', 'PreviewDark16', 'PreviewLight32', 'PreviewLight16'
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
$script:identity = New-IdentityState 'clean'
$script:checkWorker = $null
$script:checkAnswer = $null
$script:checkLastLine = ''
$script:filling = $false
$script:focusName = $false
$script:previewKey = ''
$script:previewImage = $null
$debounce = New-Object Windows.Threading.DispatcherTimer
$debounce.Interval = [TimeSpan]::FromMilliseconds(350)

function Set-ControlVisible {
    param($Control, [bool]$Visible)

    $Control.Visibility = if ($Visible) { 'Visible' } else { 'Collapsed' }
}

function Set-WizardChrome {
    $state = Get-WizardPageState -Page $script:page -Resume ([bool]$script:request.Resume) `
        -Preview ([bool]$script:request.Preview) `
        -IdentityReady ((Get-IdentityView $script:identity).Ready)
    Set-ControlVisible $controls.ChoicePane $state.ChoiceVisible
    Set-ControlVisible $controls.IdentityPane $state.IdentityVisible
    Set-ControlVisible $controls.ReviewPane $state.ReviewVisible
    Set-ControlVisible $controls.OutputPane $state.OutputVisible
    Set-ControlVisible $controls.ProgressBar $state.ProgressVisible
    Set-ControlVisible $controls.FinishActions $state.FinishVisible
    $controls.BackButton.IsEnabled = $state.BackEnabled
    Set-ControlVisible $controls.BackButton $state.BackEnabled
    $controls.CloseButton.IsEnabled = $state.CloseEnabled
    $controls.NextButton.IsEnabled = $state.NextEnabled
    Set-ControlVisible $controls.NextButton $state.NextEnabled
    $controls.NextButton.Content = $state.NextContent
    $controls.PageTitle.Text = $state.Title
}

function Show-WizardPage {
    param([string]$Page, [string]$Message = '')

    $script:page = $Page
    if ($Page -eq 'choice') { Update-ChoiceSummary }
    if ($Page -eq 'identity') { Update-IdentityPage }
    Set-WizardChrome
    $controls.PageStatus.Text = $Message
}

function Update-ChoiceSummary {
    $controls.IdentitySummary.Text = Get-IdentitySummary $script:identity
}

function Get-SelectedMode {
    if ($controls.CopyMode.IsChecked) { return 'copy' }
    return 'clean'
}

function Set-BoxText {
    param($Box, [string]$Text)

    if ($Box.Text -cne $Text) { $Box.Text = $Text }
}

function Set-FieldMessage {
    param($Block, $Box, [string]$Text)

    $Block.Text = $Text
    Set-ControlVisible $Block ($Text -ne '')
    if ($Box) { [Windows.Automation.AutomationProperties]::SetHelpText($Box, $Text) }
}

function Update-IdentityPreview {
    param($Preview)

    $key = '{0}|{1}|{2}' -f $Preview.Kind, $Preview.Path, ($Preview.Art | ConvertTo-Json -Compress)
    if ($key -ne $script:previewKey) {
        $script:previewKey = $key
        $script:previewImage = New-IdentityPreviewImage $Preview
    }
    $caption = $Preview.Caption
    if ($Preview.Kind -ne 'none' -and $null -eq $script:previewImage) { $caption = 'No preview of this image' }
    $opacity = if ($Preview.Dimmed) { 0.45 } else { 1.0 }
    foreach ($name in @('PreviewLarge', 'PreviewDark32', 'PreviewDark16', 'PreviewLight32', 'PreviewLight16')) {
        $controls[$name].Source = $script:previewImage
        $controls[$name].Opacity = $opacity
    }
    $controls.PreviewCaption.Text = $caption
    [Windows.Automation.AutomationProperties]::SetName($controls.PreviewLarge, "Icon preview: $caption")
}

function Update-IdentityPage {
    $view = Get-IdentityView $script:identity
    $script:filling = $true
    try {
        Set-BoxText $controls.IdentityName $view.NameText
        Set-BoxText $controls.IdentityMonogram $view.MonogramText
        Set-BoxText $controls.IdentityAccent $view.AccentText
        Set-BoxText $controls.IdentityIconText $view.IconText
    } finally {
        $script:filling = $false
    }
    foreach ($box in @($controls.IdentityName, $controls.IdentityMonogram, $controls.IdentityAccent)) {
        $box.IsEnabled = $view.FieldsEnabled
        $box.IsReadOnly = $view.FieldsReadOnly
    }
    $controls.PickColourButton.IsEnabled = $view.FieldsEnabled -and -not $view.FieldsReadOnly
    $controls.ChoosePngButton.IsEnabled = $view.CanChoosePng
    $controls.RemovePngButton.IsEnabled = $view.CanRemovePng
    $controls.RestoreDefaultButton.IsEnabled = $view.CanRestoreDefault
    $controls.DiscardButton.IsEnabled = $view.CanDiscard
    $controls.IdentityStatus.Text = $view.Status
    Set-ControlVisible $controls.IdentityStatus ($view.Status -ne '')
    $controls.IdentityMonogramHint.Text = $view.MonogramHint
    Set-FieldMessage $controls.IdentityNameMessage $controls.IdentityName $view.Messages['name']
    Set-FieldMessage $controls.IdentityMonogramMessage $controls.IdentityMonogram $view.Messages['monogram']
    Set-FieldMessage $controls.IdentityAccentMessage $controls.IdentityAccent $view.Messages['accent']
    Set-FieldMessage $controls.IdentityIconMessage $controls.IdentityIconText $view.Messages['icon']
    Set-FieldMessage $controls.IdentityGeneralMessage $null $view.Messages['general']
    try {
        $controls.AccentSwatch.Background = if ($view.SwatchColour) {
            New-PreviewBrush $view.SwatchColour
        } else {
            [Windows.Media.Brushes]::Transparent
        }
    } catch {
        $controls.AccentSwatch.Background = [Windows.Media.Brushes]::Transparent
    }
    Update-IdentityPreview $view.Preview
    if ($script:page -eq 'identity') {
        Set-WizardChrome
        if ($script:focusName -and $view.FieldsEnabled) {
            $script:focusName = $false
            [void]$controls.IdentityName.Focus()
        }
    }
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
            -Resume $script:request.Resume -Consent $script:request.Consent `
            -BrandJson $script:request.BrandJson
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
        $brandLines = @(Get-ReviewBrandLines $preview.brand $script:request.ChosenIcon)
        if ($brandLines.Count) { $summary += @('') + $brandLines }
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
function Stop-IdentityCheckProcess {
    if ($null -eq $script:checkWorker) { return }
    $process = $script:checkWorker.Process
    try {
        if (-not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
        }
    } catch {
        $null = $_
    }
    $process.Dispose()
    $script:checkWorker = $null
    Complete-IdentityCheckProcess $script:identity
}

function Start-IdentityProcessIfNeeded {
    if ((Get-IdentityCheckAction $script:identity) -ne 'start') { return }
    $started = Start-IdentityCheck $script:identity ([datetime]::Now)
    $script:checkAnswer = $null
    $script:checkLastLine = ''
    try {
        $script:checkWorker = Start-DeploymentWorker -ScriptPath $backend -Target '' `
            -Mode $script:identity.Mode -Preview $false -Resume $false -Consent $false `
            -BrandJson $started.BrandJson -CheckBrand $true
    } catch {
        Complete-IdentityCheckProcess $script:identity
        [void](Receive-IdentityFailure $script:identity $started.RequestId $_.Exception.Message)
        Update-IdentityPage
    }
}

function Receive-IdentityWorker {
    if ($null -eq $script:checkWorker) { return }
    $batch = Receive-DeploymentWorker $script:checkWorker
    foreach ($line in $batch.Lines) {
        $answer = ConvertFrom-BrandCheckLine $line
        if ($answer) {
            $script:checkAnswer = $answer
        } elseif ($line.Trim()) {
            $script:checkLastLine = $line.Trim()
        }
    }
    $requestId = $script:identity.InFlightId
    $timedOut = -not $batch.Done -and
        (Test-IdentityCheckTimedOut $script:identity.InFlightStartedAt ([datetime]::Now))
    if (-not $batch.Done -and -not $timedOut) { return }
    $exitCode = $batch.ExitCode
    Stop-IdentityCheckProcess
    if ($script:checkAnswer) {
        [void](Receive-IdentityAnswer $script:identity $requestId $script:checkAnswer)
    } else {
        $reason = if ($timedOut) {
            'The check did not finish.'
        } elseif ($script:checkLastLine) {
            $script:checkLastLine
        } else {
            "The check ended with code $exitCode and no answer."
        }
        [void](Receive-IdentityFailure $script:identity $requestId $reason)
    }
    Update-IdentityPage
    Update-ChoiceSummary
    if (-not $debounce.IsEnabled) { Start-IdentityProcessIfNeeded }
}

function Invoke-IdentityNow {
    $debounce.Stop()
    Update-IdentityPage
    Update-ChoiceSummary
    Start-IdentityProcessIfNeeded
}

function Edit-IdentityField {
    param([string]$Field, [string]$Text)

    if ($script:filling) { return }
    Set-IdentityText $script:identity $Field $Text
    $debounce.Stop()
    $debounce.Start()
    Update-IdentityPage
    Update-ChoiceSummary
}

function Enter-IdentityPage {
    if ($script:identity.StartStatus -eq 'unread') { Request-IdentityStart $script:identity }
    $script:focusName = $true
    Show-WizardPage 'identity'
    Start-IdentityProcessIfNeeded
}

function Sync-IdentityMode {
    $mode = Get-SelectedMode
    if ($script:identity.Mode -eq $mode) { return }
    $debounce.Stop()
    Stop-IdentityCheckProcess
    $switch = Switch-IdentityMode $script:identity $mode
    $script:identity = $switch.State
    Update-ChoiceSummary
    if ($switch.Discarded) {
        $controls.PageStatus.Text = 'Identity changes were discarded because the mode changed.'
    }
}

function Invoke-Review {
    $value = $controls.TargetText.Text.Trim()
    try {
        if ([string]::IsNullOrWhiteSpace($value)) { throw 'Choose a destination folder.' }
        $target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($value)
        $mode = Get-SelectedMode
        $phase = Get-DeploymentWizardPhase -Target $target -Mode $mode
        if ($phase -eq 'preparing') {
            $controls.PageStatus.Text = Get-DeploymentPreparationHint -Target $target
            return
        }
        $gate = Get-WizardReviewGate -RequestIsEmpty (-not (Test-IdentityHasEdits $script:identity)) `
            -CheckStatus $script:identity.CheckStatus -Phase ([string]$phase)
        if ($gate -eq 'resume-conflict') {
            Show-WizardPage 'choice' (Get-ResumeConflictMessage)
            return
        }
        if ($gate -eq 'identity') {
            Show-WizardPage 'identity' 'Wait for the identity check, then choose Review.'
            return
        }
        $resume = $phase -eq 'ready'
        $script:request = [pscustomobject]@{
            Target = $target
            Mode = $mode
            Resume = $resume
            Consent = [bool]$controls.PythonConsent.IsChecked
            Preview = $true
            BrandJson = if ($resume) { '' } else { ConvertTo-BrandRequestJson (Get-BrandRequest $script:identity) }
            ChosenIcon = [string]$script:identity.IconPath
            CameFromIdentity = ($script:page -eq 'identity')
        }
        Start-WizardStep $true
    } catch {
        $controls.PageStatus.Text = $_.Exception.Message
    }
}

$checkTimer = New-Object Windows.Threading.DispatcherTimer
$checkTimer.Interval = [TimeSpan]::FromMilliseconds(100)
$checkTimer.Add_Tick({
    try { Receive-IdentityWorker } catch { $controls.PageStatus.Text = $_.Exception.Message }
})
$debounce.Add_Tick({
    $debounce.Stop()
    Start-IdentityProcessIfNeeded
})
$controls.CleanMode.Add_Checked({ Sync-IdentityMode })
$controls.CopyMode.Add_Checked({ Sync-IdentityMode })
$controls.CustomizeButton.Add_Click({ Enter-IdentityPage })
$controls.IdentityName.Add_TextChanged({ Edit-IdentityField 'name' $controls.IdentityName.Text })
$controls.IdentityMonogram.Add_TextChanged({ Edit-IdentityField 'monogram' $controls.IdentityMonogram.Text })
$controls.IdentityAccent.Add_TextChanged({ Edit-IdentityField 'accent' $controls.IdentityAccent.Text })
$controls.PickColourButton.Add_Click({
    $dialog = New-Object Windows.Forms.ColorDialog
    try {
        $dialog.FullOpen = $true
        if ($dialog.ShowDialog() -eq 'OK') {
            $colour = $dialog.Color
            $controls.IdentityAccent.Text = '#{0:X2}{1:X2}{2:X2}' -f $colour.R, $colour.G, $colour.B
        }
    } finally {
        $dialog.Dispose()
    }
})
$controls.ChoosePngButton.Add_Click({
    $picker = New-Object Microsoft.Win32.OpenFileDialog
    $picker.Title = 'Choose a PNG image for the icon'
    $picker.Filter = 'PNG image (*.png)|*.png'
    $picker.CheckFileExists = $true
    if ($picker.ShowDialog($window)) {
        Set-IdentityIcon $script:identity $picker.FileName
        Invoke-IdentityNow
    }
})
$controls.RemovePngButton.Add_Click({
    Remove-IdentityIcon $script:identity
    Invoke-IdentityNow
})
$controls.RestoreDefaultButton.Add_Click({
    Use-DefaultIdentity $script:identity
    Invoke-IdentityNow
})
$controls.DiscardButton.Add_Click({
    Reset-IdentityEdits $script:identity
    Invoke-IdentityNow
})
$controls.NextButton.Add_Click({
    if ($script:page -in @('choice', 'identity')) {
        Invoke-Review
    } elseif ($script:page -in @('review', 'retry')) {
        Start-WizardStep $false
    }
})
$controls.BackButton.Add_Click({
    $target = Get-WizardBackTarget -Page $script:page -CameFromIdentity ([bool]$script:request.CameFromIdentity)
    Show-WizardPage $(if ($target) { $target } else { 'choice' })
})
$controls.CloseButton.Add_Click({ $window.Close() })
$window.Add_Closing({
    param($sender, $eventArgs)
    if ($script:worker) {
        $eventArgs.Cancel = $true
        $controls.PageStatus.Text = 'Wait for the current step to finish before closing.'
        return
    }
    $debounce.Stop()
    Stop-IdentityCheckProcess
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
$checkTimer.Start()
try { [void]$window.ShowDialog() } finally { $timer.Stop(); $checkTimer.Stop(); $debounce.Stop() }
