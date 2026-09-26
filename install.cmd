@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install\bootstrap.ps1" %*
set "INSTALL_EXIT_CODE=%ERRORLEVEL%"
setlocal EnableDelayedExpansion
set "LAUNCH_LINE=!cmdcmdline!"
rem A cmd started only to run this script (Explorer double-click) names it on its command line and closes when it ends.
if /i not "!LAUNCH_LINE:%~f0=!"=="!LAUNCH_LINE!" pause
exit /b %INSTALL_EXIT_CODE%
