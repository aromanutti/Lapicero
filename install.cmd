@echo off
rem Double-click to install Lapicero. Arguments are passed through (-Yes, -CheckOnly).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
