@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Jarvis is not installed yet. Run install.cmd first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m jarvis.launcher
