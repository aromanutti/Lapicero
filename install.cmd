@echo off
rem Double-click to install Lapicero. Arguments are passed through (-Yes, -CheckOnly).
rem The window only waits for a key when started without arguments (double-click),
rem so "install.cmd -Yes" runs unattended. The exit code is the installer's (1 = a
rem required piece is missing).
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "code=%ERRORLEVEL%"
if "%~1"=="" (
    echo.
    pause
)
exit /b %code%
