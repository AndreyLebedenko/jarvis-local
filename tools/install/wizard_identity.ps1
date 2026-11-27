# State and rules of the wizard's Identity page. Pure functions over one
# hashtable: no controls, no processes. The brand rules themselves are never
# decided here; every answer about validity comes from the deployment tool.

$script:IdentityCheckTimeoutSeconds = 20
$script:IdentityMessageLimit = 300

function New-IdentityState {
    param([string]$Mode, [string]$HomeFolder = '')

    return @{
        Mode = $Mode
        Home = $HomeFolder
        Start = $null
        StartAnswer = $null
        StartStatus = 'unread'
        NameText = ''
        AccentText = ''
        MonogramText = ''
        IconPath = $null
        NoIcon = $false
        UseDefault = $false
        RequestId = 0
        StartedId = -1
        InFlightId = $null
        InFlightStartedAt = $null
        CheckStatus = 'idle'
        Answer = $null
        LastOk = $null
        Messages = @{ name = ''; monogram = ''; accent = ''; icon = ''; general = '' }
    }
}

function Format-IdentityMessage {
    param([string]$Text)

    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $blocked = @(
        [Globalization.UnicodeCategory]::Control, [Globalization.UnicodeCategory]::Format,
        [Globalization.UnicodeCategory]::Surrogate, [Globalization.UnicodeCategory]::PrivateUse,
        [Globalization.UnicodeCategory]::OtherNotAssigned,
        [Globalization.UnicodeCategory]::LineSeparator,
        [Globalization.UnicodeCategory]::ParagraphSeparator
    )
    $builder = New-Object Text.StringBuilder
    $index = 0
    while ($index -lt $Text.Length -and $builder.Length -lt $script:IdentityMessageLimit) {
        $pair = [char]::IsHighSurrogate($Text[$index]) -and $index + 1 -lt $Text.Length -and
            [char]::IsLowSurrogate($Text[$index + 1])
        $width = if ($pair) { 2 } else { 1 }
        if ($blocked -contains [Globalization.CharUnicodeInfo]::GetUnicodeCategory($Text, $index)) {
            [void]$builder.Append([char]0xFFFD)
        } else {
            [void]$builder.Append($Text.Substring($index, $width))
        }
        $index += $width
    }
    if ($index -lt $Text.Length) { [void]$builder.Append('...') }
    return $builder.ToString()
}

function Get-BrandRequest {
    param($State)

    if ($State.UseDefault) { return [ordered]@{ default_brand = $true } }
    $request = [ordered]@{}
    $startName = if ($State.Start) { [string]$State.Start.name } else { '' }
    $startAccent = if ($State.Start) { [string]$State.Start.accent } else { '' }
    $unknownStart = $null -eq $State.Start
    if (-not ($unknownStart -and $State.NameText -eq '') -and $State.NameText -cne $startName) {
        $request['name'] = $State.NameText
    }
    if ($State.MonogramText -ne '') { $request['monogram'] = $State.MonogramText }
    if (-not ($unknownStart -and $State.AccentText -eq '') -and $State.AccentText -ine $startAccent) {
        $request['accent'] = $State.AccentText
    }
    if ($State.IconPath) { $request['icon'] = $State.IconPath }
    if ($State.NoIcon) { $request['no_icon'] = $true }
    if ($request.Count -eq 0) { return $null }
    return $request
}

function ConvertTo-BrandRequestJson {
    param($Request)

    if ($null -eq $Request) { return '' }
    return ($Request | ConvertTo-Json -Compress)
}

function Test-IdentityHasEdits {
    param($State)

    return $null -ne (Get-BrandRequest $State)
}

function Test-IdentityAnswerIsCurrent {
    param($State, [int]$RequestId)

    return $RequestId -eq $State.RequestId
}

function Test-IdentityCheckTimedOut {
    param([datetime]$StartedAt, [datetime]$Now)

    return ($Now - $StartedAt).TotalSeconds -ge $script:IdentityCheckTimeoutSeconds
}

function Clear-IdentityMessages {
    param($State)

    foreach ($key in @('name', 'monogram', 'accent', 'icon', 'general')) { $State.Messages[$key] = '' }
}

function Set-IdentityPending {
    param($State)

    $State.RequestId++
    Clear-IdentityMessages $State
    $request = Get-BrandRequest $State
    if ($null -eq $request -and $State.StartStatus -eq 'read') {
        $State.Answer = $State.StartAnswer
        $State.LastOk = $State.StartAnswer
        $State.CheckStatus = 'ok'
    } else {
        $State.CheckStatus = 'pending'
    }
}

function Set-IdentityText {
    param($State, [ValidateSet('name', 'monogram', 'accent')][string]$Field, [string]$Text)

    if ($State.UseDefault -or $State.StartStatus -eq 'loading') { return }
    switch ($Field) {
        'name' { $State.NameText = $Text }
        'monogram' { $State.MonogramText = $Text }
        'accent' { $State.AccentText = $Text }
    }
    Set-IdentityPending $State
}

function Set-IdentityIcon {
    param($State, [string]$Path)

    if ($State.UseDefault -or $State.StartStatus -eq 'loading') { return }
    $State.IconPath = $Path
    $State.NoIcon = $false
    Set-IdentityPending $State
}

function Remove-IdentityIcon {
    param($State)

    if ($State.UseDefault -or $State.StartStatus -eq 'loading') { return }
    $State.IconPath = $null
    $State.NoIcon = [bool]($State.Start -and $State.Start.icon)
    Set-IdentityPending $State
}

function Use-DefaultIdentity {
    param($State)

    if ($State.StartStatus -eq 'loading') { return }
    $State.UseDefault = $true
    $State.IconPath = $null
    $State.NoIcon = $false
    Set-IdentityPending $State
}

function Reset-IdentityEdits {
    param($State)

    if ($State.StartStatus -eq 'loading') { return }
    $State.UseDefault = $false
    $State.IconPath = $null
    $State.NoIcon = $false
    $State.MonogramText = ''
    $State.NameText = if ($State.Start) { [string]$State.Start.name } else { '' }
    $State.AccentText = if ($State.Start) { [string]$State.Start.accent } else { '' }
    Set-IdentityPending $State
}

function Request-IdentityStart {
    param($State)

    $State.StartStatus = 'loading'
    $State.RequestId++
    $State.CheckStatus = 'loading'
    Clear-IdentityMessages $State
}

function Switch-IdentityMode {
    param($State, [string]$Mode)

    return [pscustomobject]@{
        State = New-IdentityState $Mode
        Discarded = (Test-IdentityHasEdits $State)
    }
}

function Get-IdentityCheckAction {
    param($State)

    if ($null -ne $State.InFlightId) { return 'wait' }
    if ($State.CheckStatus -in @('pending', 'loading') -and $State.RequestId -ne $State.StartedId) {
        return 'start'
    }
    return 'idle'
}

function Start-IdentityCheck {
    param($State, [datetime]$Now)

    $State.InFlightId = $State.RequestId
    $State.StartedId = $State.RequestId
    $State.InFlightStartedAt = $Now
    return [pscustomobject]@{
        RequestId = $State.RequestId
        BrandJson = (ConvertTo-BrandRequestJson (Get-BrandRequest $State))
    }
}

function Complete-IdentityCheckProcess {
    param($State)

    $State.InFlightId = $null
    $State.InFlightStartedAt = $null
}

function Receive-IdentityAnswer {
    param($State, [int]$RequestId, $Answer)

    if (-not (Test-IdentityAnswerIsCurrent $State $RequestId)) { return $false }
    $loading = $State.StartStatus -eq 'loading'
    $State.Answer = $Answer
    Clear-IdentityMessages $State
    if ($Answer.ok) {
        $State.CheckStatus = 'ok'
        $State.LastOk = $Answer
        if ($loading) {
            $State.Start = $Answer.brand
            $State.StartAnswer = $Answer
            $State.StartStatus = 'read'
            $State.NameText = [string]$Answer.brand.name
            $State.AccentText = [string]$Answer.brand.accent
        }
        return $true
    }
    $State.CheckStatus = 'invalid'
    if ($loading) { $State.StartStatus = 'failed' }
    $text = Format-IdentityMessage ([string]$Answer.message)
    $field = [string]$Answer.field
    if ($field -in @('name', 'monogram', 'accent', 'icon')) {
        $State.Messages[$field] = $text
    } else {
        $State.Messages['general'] = $text
    }
    if ($loading -and $State.Mode -eq 'copy') {
        $State.Messages['general'] = 'The identity of the source is not valid. Correct the values or restore the default identity.'
    }
    return $true
}

function Receive-IdentityFailure {
    param($State, [int]$RequestId, [string]$Reason)

    if (-not (Test-IdentityAnswerIsCurrent $State $RequestId)) { return $false }
    $loading = $State.StartStatus -eq 'loading'
    $State.Answer = $null
    Clear-IdentityMessages $State
    $State.CheckStatus = 'unavailable'
    if ($loading) { $State.StartStatus = 'failed' }
    $reasonText = (Format-IdentityMessage $Reason).TrimEnd()
    if ($reasonText -eq '') { $reasonText = 'No reason was reported' }
    if (-not $reasonText.EndsWith('.')) { $reasonText += '.' }
    $what = if ($loading) { 'read the current identity' } else { 'check the identity' }
    $State.Messages['general'] = "Could not $what now: $reasonText It is checked again at Review."
    return $true
}

function Get-IdentityPreview {
    param($State)

    $none = { param($caption) [pscustomobject]@{ Kind = 'none'; Art = $null; Path = $null; Dimmed = $false; Caption = $caption } }
    if ($State.CheckStatus -eq 'ok') { $source = $State.Answer; $dimmed = $false }
    elseif ($State.CheckStatus -eq 'pending' -and $State.LastOk) { $source = $State.LastOk; $dimmed = $true }
    else {
        $caption = if ($State.CheckStatus -eq 'invalid') { 'No preview while the identity is not valid' }
        elseif ($State.CheckStatus -in @('loading', 'pending')) { 'Reading...' }
        else { 'Preview unavailable' }
        return & $none $caption
    }
    $brand = $source.brand
    $preview = $source.icon_preview
    $caption = switch ($preview.kind) {
        'monogram' { "Generated monogram $($brand.monogram) on accent $($brand.accent)" }
        'image' { 'Your PNG image, centred' }
        'packaged' { 'The standard Jarvis icon' }
    }
    return [pscustomobject]@{
        Kind = [string]$preview.kind
        Art = $preview.art
        Path = $preview.path
        Dimmed = $dimmed
        Caption = $caption
    }
}

function Get-IdentityIconText {
    param($State)

    if ($State.UseDefault) { return 'The standard Jarvis icon' }
    if ($State.IconPath) { return [string]$State.IconPath }
    if ($State.NoIcon) { return 'No PNG: a generated monogram is used' }
    if ($State.Start -and $State.Start.icon) {
        $label = if ($State.Mode -eq 'rebrand') { 'Current PNG' } else { 'Inherited from the source' }
        return "${label}: $($State.Start.icon)"
    }
    return 'No PNG: a generated monogram is used'
}

function Get-IdentityView {
    param($State)

    $loading = $State.StartStatus -eq 'loading'
    $shown = $State.UseDefault -and $State.CheckStatus -eq 'ok'
    $hasIcon = [bool]($State.IconPath -or ($State.Start -and $State.Start.icon -and -not $State.NoIcon))
    $monogram = if ($State.LastOk) { [string]$State.LastOk.brand.monogram }
    $rebrand = $State.Mode -eq 'rebrand'
    $nothingToChange = $rebrand -and $State.CheckStatus -eq 'ok' -and -not (Test-IdentityHasEdits $State)
    $status = switch ($State.CheckStatus) {
        'loading' { 'Reading the current identity...' }
        'pending' { 'Updating...' }
        default { if ($nothingToChange) { 'Change at least one value to continue.' } else { '' } }
    }
    $checked = if ($rebrand) { @('ok') } else { @('ok', 'unavailable') }
    $canChange = -not $loading -and -not $State.UseDefault
    return [pscustomobject]@{
        NameText = if ($shown) { [string]$State.Answer.brand.name } else { $State.NameText }
        AccentText = if ($shown) { [string]$State.Answer.brand.accent } else { $State.AccentText }
        MonogramText = if ($shown) { '' } else { $State.MonogramText }
        MonogramHint = if ($monogram) { "Empty keeps the current letter: $monogram" } else { 'Empty keeps the automatic letter' }
        SwatchColour = if ($State.LastOk) { [string]$State.LastOk.brand.accent } else { '' }
        FieldsEnabled = -not $loading
        FieldsReadOnly = [bool]$State.UseDefault
        IconText = Get-IdentityIconText $State
        CanChoosePng = $canChange
        CanRemovePng = $canChange -and $hasIcon
        CanRestoreDefault = ($State.Mode -in @('copy', 'rebrand')) -and $canChange -and (
            $State.StartStatus -eq 'failed' -or ($State.Start -and -not $State.Start.is_default))
        CanDiscard = -not $loading -and (Test-IdentityHasEdits $State)
        Ready = ($State.CheckStatus -in $checked) -and -not $loading -and -not $nothingToChange
        Status = $status
        Messages = $State.Messages.Clone()
        Preview = Get-IdentityPreview $State
    }
}

function Get-IdentitySummary {
    param($State)

    $request = Get-BrandRequest $State
    if ($null -eq $request) {
        if ($State.Mode -eq 'copy') { return 'Identity: same as the source' }
        return 'Identity: default'
    }
    if ($request.Contains('default_brand')) { return 'Identity: the default Jarvis identity' }
    $labels = [ordered]@{ name = 'name'; monogram = 'letter'; accent = 'accent'; icon = 'PNG'; no_icon = 'PNG removed' }
    $changed = @($labels.Keys | Where-Object { $request.Contains($_) } | ForEach-Object { $labels[$_] })
    return 'Identity: changed (' + ($changed -join ', ') + ')'
}

function Get-ReviewBrandLines {
    param($Brand, [string]$ChosenIconPath = '')

    if ($null -eq $Brand -or $Brand.is_default) { return @() }
    $origin = if ($Brand.origin -eq 'inherited') { 'inherited from the source' } else { 'changed' }
    $lines = @("Identity: $($Brand.name) ($origin)")
    if ($Brand.icon) {
        $copy = if ($Brand.origin -eq 'requested' -and $ChosenIconPath) { " (copy of $ChosenIconPath)" } else { '' }
        $lines += "Icon image: $($Brand.icon)$copy"
    } else {
        $lines += "Monogram: $($Brand.monogram) on $($Brand.accent)"
    }
    return $lines
}

function Get-RebrandReviewLines {
    param([string]$HomeFolder, $Brand, [string]$ChosenIconPath = '')

    $lines = @('Change the identity of an existing Jarvis home.', "Home: $HomeFolder", '')
    if ($Brand.is_default) {
        $lines += @(
            'Identity: the default Jarvis identity', '', 'Files that will change:',
            '  config.toml: the [brand] section is removed',
            '  brand\ and brand-source\ stay as they are; Jarvis ignores them'
        )
    } else {
        $lines += "Identity: $($Brand.name) (changed)"
        $lines += if ($Brand.icon) { "Icon image: $($Brand.icon)" } else { "Monogram: $($Brand.monogram) on $($Brand.accent)" }
        $lines += @('', 'Files that will change:', '  config.toml: the [brand] section')
        if ($ChosenIconPath) { $lines += "  brand-source\icon.png: a copy of $ChosenIconPath" }
        $lines += '  brand\brand.png and brand\brand.ico: regenerated'
    }
    return $lines + @('', 'Everything else in the home stays as it is.')
}

function Get-RebrandFinishLines {
    param($Result)

    $lines = @(
        'The identity of this home was changed.',
        "Written: $(@($Result.files) -join ', ')",
        '',
        'The Status Console and window titles change when Jarvis starts next.',
        'The tray name and icon change at the next mode start from the tray, or after Regenerate icons.',
        'A shortcut you saved earlier keeps its name; save a new one to get the new name and icon.'
    )
    if ($Result.brand.is_default) {
        $lines += 'A shortcut that points at brand\brand.ico keeps showing the old icon, because that file stays.'
    }
    return $lines
}
