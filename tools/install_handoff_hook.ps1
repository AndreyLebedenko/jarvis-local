# Install/refresh the handoff self-sufficiency pre-commit hook.

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$hookPath = Join-Path (Join-Path $repoRoot ".git") "hooks\pre-commit"

$hookTemplate = Get-Content -Raw -Encoding UTF8 (Join-Path (Join-Path $PSScriptRoot "hooks") "pre-commit-handoff-check.sh")

# Git for Windows runs hooks through sh, which rejects a UTF-8 BOM before
# the shebang. PowerShell's -Encoding UTF8 always writes a BOM on 5.1, so
# write BOM-less UTF-8 explicitly.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$existing = $null
if (Test-Path -LiteralPath $hookPath) {
    $existing = Get-Content -Raw -Encoding UTF8 $hookPath
}

if ($existing -and $existing.Contains("jarvis-handoff-hook-start")) {
    # Already installed - keep a single copy, refresh the block in place.
    $updated = $existing -replace
        "(?s)# jarvis-handoff-hook-start.*?# jarvis-handoff-hook-end",
        ("# jarvis-handoff-hook-start`n" +
         ($hookTemplate -replace "^#!.*?`n", "") +
         "jarvis-handoff-hook-end")
    [System.IO.File]::WriteAllText($hookPath, $updated, $utf8NoBom)
    Write-Output "pre-commit hook refreshed at $hookPath"
} elseif ($existing) {
    # Another tool owns the hook (e.g. graphify's post-commit only; pre-commit
    # may still be taken). Append a marked block instead of overwriting.
    $combined = $existing.TrimEnd() + "`n`n" + $hookTemplate
    [System.IO.File]::WriteAllText($hookPath, $combined, $utf8NoBom)
    Write-Output "pre-commit hook appended (existing hook preserved) at $hookPath"
} else {
    [System.IO.File]::WriteAllText($hookPath, $hookTemplate, $utf8NoBom)
    Write-Output "pre-commit hook installed at $hookPath"
}

Write-Output "Use git config core.hooksPath only if you move hooks deliberately;"
Write-Output "the default .git/hooks path is expected."