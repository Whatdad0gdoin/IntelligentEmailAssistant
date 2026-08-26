# Starts both dev servers in their own windows.
#
# Run this from a terminal YOU own, not from an agent session: a server started
# inside an agent's shell is a child of that shell and dies when the session
# ends, which surfaces in the browser as "Cannot reach the API server".
#
#   .\start-dev.ps1
#
# Close the two windows that open to stop the servers.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Test-Path "$root\backend\.env")) {
    Write-Host "backend\.env is missing. Copy backend\.env.example and fill it in." -ForegroundColor Red
    exit 1
}

Write-Host "Starting Flask on http://localhost:5000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command", "Set-Location '$root'; python -m backend.run"
)

Write-Host "Starting Vite on http://localhost:5173 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"
)

Write-Host ""
Write-Host "Both starting in separate windows. Give them a few seconds, then open:" -ForegroundColor Green
Write-Host "  http://localhost:5173" -ForegroundColor Green
