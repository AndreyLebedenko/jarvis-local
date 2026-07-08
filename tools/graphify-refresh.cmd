@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0graphify.ps1" refresh %*
exit /b %ERRORLEVEL%
