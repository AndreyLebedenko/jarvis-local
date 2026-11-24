@echo off
setlocal
powershell -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0tools\install\wizard_start.ps1"
exit /b %ERRORLEVEL%
