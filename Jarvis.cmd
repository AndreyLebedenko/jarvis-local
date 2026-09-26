@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Jarvis is not installed yet. Run install.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m jarvis --status-console %*
exit /b %ERRORLEVEL%
