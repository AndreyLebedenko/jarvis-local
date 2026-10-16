param(
    [string] $Destination = [Environment]::GetFolderPath("Desktop")
)

$ErrorActionPreference = "Stop"
$appHome = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $appHome ".venv\Scripts\pythonw.exe"
$icon = Join-Path $appHome "src\jarvis\launcher\assets\jarvis.ico"
foreach ($required in @($pythonw, $icon)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required launcher file is missing: $required. Run install.cmd first."
    }
}
if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    throw "Shortcut destination does not exist: $Destination"
}
$shortcutPath = Join-Path (Resolve-Path -LiteralPath $Destination).Path "Jarvis Launcher.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ($shortcut.TargetPath -and $shortcut.TargetPath -ne $pythonw) {
    throw "An unrelated shortcut already exists: $shortcutPath"
}
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m jarvis.launcher"
$shortcut.WorkingDirectory = $appHome
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "Jarvis Launcher - Assistant and MCP"
$shortcut.Save()
Write-Output "Created: $shortcutPath"
