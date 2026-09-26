param([switch]$Yes)

$ErrorActionPreference = 'Stop'

$PythonDownloadLink = 'https://www.python.org/downloads/release/python-3119/'
$OllamaDownloadLink = 'https://ollama.com/download'

function Stop-Bootstrap {
    param([string]$Message, [switch]$WithPythonLink)
    Write-Host "ERROR: $Message" -ForegroundColor Red
    if ($WithPythonLink) {
        Write-Host "Install Python 3.11 manually from $PythonDownloadLink, then re-run install.cmd."
    }
    exit 1
}

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue)
}

function Get-NativeOutputLine {
    param([string]$Exe, [string[]]$Arguments)
    # Windows PowerShell turns redirected native stderr into error records; under Stop the first line would abort the probe.
    $ErrorActionPreference = 'Continue'
    $output = & $Exe @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return [string]($output | Select-Object -Last 1)
}

function Test-IsPython311 {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
        return $false
    }
    $version = Get-NativeOutputLine $Exe @('-c', "import sys; print('%d.%d' % sys.version_info[:2])")
    return $version -eq '3.11'
}

function Get-PyLauncherPython311 {
    if (-not (Test-CommandAvailable 'py')) {
        return $null
    }
    return Get-NativeOutputLine 'py' @('-3.11', '-c', 'import sys; print(sys.executable)')
}

function Get-StandardPython311Path {
    return Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
}

function Get-StandardOllamaPath {
    return Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
}

function Get-CommandPath {
    param([string]$Name)
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        return $command.Source
    }
    return $null
}

function Find-Python311 {
    $candidates = @(
        (Get-PyLauncherPython311),
        (Get-CommandPath 'python3.11'),
        (Get-CommandPath 'python'),
        (Get-StandardPython311Path)
    )
    foreach ($candidate in $candidates) {
        if (Test-IsPython311 $candidate) {
            return $candidate
        }
    }
    return $null
}

function Find-Ollama {
    $onPath = Get-CommandPath 'ollama'
    if ($onPath) {
        return $onPath
    }
    $standardPath = Get-StandardOllamaPath
    if (Test-Path -LiteralPath $standardPath -PathType Leaf) {
        return $standardPath
    }
    return $null
}

function Write-Detection {
    param([string]$Name, [string]$Path)
    if ($Path) {
        Write-Host "${Name}: $Path"
    } else {
        Write-Host "${Name}: not found"
    }
}

function Assert-OllamaInstalled {
    $ollama = Find-Ollama
    if (-not $ollama) {
        Stop-Bootstrap "Ollama is required but was not found on PATH or at $(Get-StandardOllamaPath). Install it from $OllamaDownloadLink, then re-run install.cmd."
    }
    Write-Detection 'Ollama' $ollama
}

function Get-PythonWingetArguments {
    param([bool]$AcceptAgreements)
    $arguments = @('install', '--exact', '--id', 'Python.Python.3.11', '--scope', 'user')
    if ($AcceptAgreements) {
        $arguments += @('--accept-package-agreements', '--accept-source-agreements')
    }
    return $arguments
}

function Assert-WingetAvailable {
    if (-not (Test-CommandAvailable 'winget')) {
        Stop-Bootstrap 'winget is not available, so Python 3.11 cannot be installed automatically.' -WithPythonLink
    }
}

function Confirm-PythonInstall {
    param([bool]$AssumeYes)
    Write-Host 'Python 3.11 will be installed with:'
    Write-Host ('  winget ' + ((Get-PythonWingetArguments -AcceptAgreements $AssumeYes) -join ' '))
    if ($AssumeYes) {
        return
    }
    $answer = Read-Host 'Proceed? [y/N]'
    if ($answer -notmatch '^\s*(y|yes)\s*$') {
        Stop-Bootstrap 'Installation declined.' -WithPythonLink
    }
}

function Install-Python311 {
    param([bool]$AssumeYes)
    Assert-WingetAvailable
    Confirm-PythonInstall -AssumeYes $AssumeYes
    Write-Host 'Installing Python 3.11 with winget...'
    $arguments = Get-PythonWingetArguments -AcceptAgreements $AssumeYes
    & winget @arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-Bootstrap ('winget failed to install Python 3.11 (exit code 0x{0:X8}).' -f $LASTEXITCODE) -WithPythonLink
    }
}

function Get-VenvDir {
    param([string]$AppHome)
    return Join-Path $AppHome '.venv'
}

function Get-VenvPython {
    param([string]$AppHome)
    return Join-Path (Get-VenvDir $AppHome) 'Scripts\python.exe'
}

function Test-VenvReady {
    param([string]$AppHome)
    $venvDir = Get-VenvDir $AppHome
    if (Test-Path -LiteralPath (Get-VenvPython $AppHome) -PathType Leaf) {
        if (-not (Test-IsPython311 (Get-VenvPython $AppHome))) {
            Stop-Bootstrap "The existing virtual environment $venvDir is not Python 3.11. The installer never deletes it; move or remove it yourself, then re-run install.cmd."
        }
        return $true
    }
    if (Test-Path -LiteralPath $venvDir) {
        Stop-Bootstrap "$venvDir exists but contains no Scripts\python.exe. The installer never modifies it; move or remove it yourself, then re-run install.cmd."
    }
    return $false
}

function New-Venv {
    param([string]$AppHome, [string]$Python)
    $venvDir = Get-VenvDir $AppHome
    Write-Host "Creating virtual environment $venvDir"
    & $Python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Stop-Bootstrap "Creating the virtual environment failed (exit code $LASTEXITCODE)."
    }
}

function Initialize-Venv {
    param([string]$AppHome, [bool]$AssumeYes)
    if (Test-VenvReady $AppHome) {
        Write-Host "Virtual environment: already present ($(Get-VenvDir $AppHome))"
        return
    }
    $python = Find-Python311
    Write-Detection 'Python 3.11' $python
    if (-not $python) {
        Install-Python311 -AssumeYes $AssumeYes
        # winget's PATH update reaches only new processes; Find-Python311 falls back to the standard install path.
        $python = Find-Python311
        if (-not $python) {
            Stop-Bootstrap "Python 3.11 was installed but not found at $(Get-StandardPython311Path). Open a new console and re-run install.cmd."
        }
        Write-Detection 'Python 3.11' $python
    }
    New-Venv -AppHome $AppHome -Python $python
}

function Invoke-Stage2 {
    param([string]$AppHome)
    Set-Location -LiteralPath $AppHome
    & (Get-VenvPython $AppHome) (Join-Path $AppHome 'tools\installer.py')
    exit $LASTEXITCODE
}

function Invoke-Bootstrap {
    param([bool]$AssumeYes)
    $appHome = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    Write-Host "Jarvis installer, stage 1 (app home: $appHome)"
    Assert-OllamaInstalled
    Initialize-Venv -AppHome $appHome -AssumeYes $AssumeYes
    Invoke-Stage2 -AppHome $appHome
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-Bootstrap -AssumeYes $Yes.IsPresent
}
