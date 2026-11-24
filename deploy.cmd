@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install\deploy.ps1" %*
exit /b %ERRORLEVEL%
