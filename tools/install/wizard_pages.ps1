function Get-WizardPageState {
    param([string]$Page, [bool]$Resume = $false, [bool]$Preview = $false, [bool]$IdentityReady = $true)

    $nextContent = switch ($Page) {
        'choice' { 'Review' }
        'identity' { 'Review' }
        'review' { if ($Resume) { 'Resume installation' } else { 'Deploy' } }
        'retry' { 'Resume installation' }
        default { 'Continue' }
    }
    $title = switch ($Page) {
        'choice' { 'Deploy Jarvis' }
        'identity' { 'Customize identity' }
        'review' { 'Review deployment' }
        'busy' { if ($Preview) { 'Checking deployment' } else { 'Deploying Jarvis' } }
        'retry' { 'Installation needs attention' }
        'error' { 'Deployment could not continue' }
        'finish' { 'Jarvis is ready' }
    }
    return [pscustomobject]@{
        Title = $title
        ChoiceVisible = $Page -eq 'choice'
        IdentityVisible = $Page -eq 'identity'
        ReviewVisible = $Page -eq 'review'
        OutputVisible = $Page -notin @('choice', 'identity', 'review')
        ProgressVisible = $Page -eq 'busy'
        FinishVisible = $Page -eq 'finish'
        BackEnabled = $Page -in @('identity', 'review', 'retry', 'error')
        NextEnabled = ($Page -in @('choice', 'review', 'retry')) -or ($Page -eq 'identity' -and $IdentityReady)
        NextContent = $nextContent
        CloseEnabled = $Page -ne 'busy'
    }
}

function Get-WizardBackTarget {
    param([string]$Page, [bool]$CameFromIdentity = $false)

    switch ($Page) {
        'review' { if ($CameFromIdentity) { 'identity' } else { 'choice' } }
        { $_ -in @('identity', 'retry', 'error') } { 'choice' }
    }
}

function Get-WizardReviewGate {
    param([bool]$RequestIsEmpty, [string]$CheckStatus, [string]$Phase)

    if ($RequestIsEmpty) { return 'go' }
    if ($Phase -eq 'ready') { return 'resume-conflict' }
    if ($CheckStatus -in @('loading', 'pending', 'invalid')) { return 'identity' }
    return 'go'
}

function Get-ResumeConflictMessage {
    return 'This folder holds a prepared deployment; it resumes with the identity it was prepared with. Discard the identity changes or choose another folder.'
}
