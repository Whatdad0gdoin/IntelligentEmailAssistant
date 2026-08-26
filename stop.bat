@echo off
REM Double-click this to stop both servers.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Stop
