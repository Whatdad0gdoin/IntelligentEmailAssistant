@echo off
REM Double-click this to start everything.
REM
REM It calls start.ps1 with -ExecutionPolicy Bypass, because Windows blocks
REM double-clicked .ps1 files by default and that stops the script before it
REM prints anything, which looks like nothing happened.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
  echo.
  echo Startup did not complete. Read the messages above.
  pause
)
