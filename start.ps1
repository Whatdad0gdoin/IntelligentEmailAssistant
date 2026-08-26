# Intelligent Email Assistant - one-command start.
#
#   .\start.ps1              start everything
#   .\start.ps1 -Stop        stop everything
#   .\start.ps1 -SkipInstall skip the dependency check (faster restart)
#
# Or just double-click start.bat, which calls this and bypasses the PowerShell
# execution policy that otherwise blocks double-clicked .ps1 files.
#
# Checks prerequisites, installs anything missing, frees the ports, starts both
# servers in their own windows, waits until they actually answer, and opens the
# browser. Run it from a terminal you own: a server started inside an agent
# session is a child of that shell and dies when the session ends.

param(
    [switch]$Stop,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$BackendPort = 5000
$FrontendPort = 5173

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }
function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    OK   $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    WARN $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "    FAIL $text" -ForegroundColor Red }

function Stop-Port($port, $label) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        foreach ($procId in ($conn.OwningProcess | Select-Object -Unique)) {
            try { Stop-Process -Id $procId -Force -ErrorAction Stop; Ok "stopped $label (PID $procId)" }
            catch { Warn "could not stop PID $procId on port $port" }
        }
        Start-Sleep -Seconds 2
        return $true
    }
    return $false
}

function Wait-ForPort($port, $label, $seconds = 45) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            Ok "$label is listening on $port"
            return $true
        }
        Start-Sleep -Seconds 1
    }
    Fail "$label did not start within $seconds seconds - check its window for the error"
    return $false
}

# --------------------------------------------------------------------- stop

if ($Stop) {
    Step "Stopping servers"
    $a = Stop-Port $BackendPort "backend"
    $b = Stop-Port $FrontendPort "frontend"
    if (-not ($a -or $b)) { Say "    nothing was running" }
    Write-Host ""
    exit 0
}

Write-Host ""
Say "  Intelligent Email Assistant - FIT3164 DS-25" "White"
Say "  ------------------------------------------" "DarkGray"

# ------------------------------------------------------------ prerequisites

Step "Checking prerequisites"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Fail "Python is not on PATH. Install Python 3.12+ and reopen this terminal."; exit 1 }
Ok "python $((python --version 2>&1) -replace 'Python ')"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail "Node.js is not on PATH. Install Node 20+ and reopen this terminal."; exit 1 }
Ok "node $(node --version)"

# ------------------------------------------------------------------- config

Step "Checking configuration"

$envFile = Join-Path $root "backend\.env"
if (-not (Test-Path $envFile)) {
    Warn "backend\.env is missing - creating it from the example"
    Copy-Item (Join-Path $root "backend\.env.example") $envFile
    Say ""
    Say "    backend\.env was created but is NOT filled in yet. You need to:" "Yellow"
    Say "      1. Set JWT_SECRET:  python -c ""import secrets; print(secrets.token_urlsafe(48))""" "Yellow"
    Say "      2. Add an account:  python -m backend.scripts.hash_password" "Yellow"
    Say "      3. Set OPENAI_API_KEY (the AI features cannot run without it)" "Yellow"
    Say ""
    Say "    Then run this script again." "Yellow"
    exit 1
}

$envText = Get-Content $envFile -Raw
foreach ($pair in @(
    @("JWT_SECRET", "logging in will fail"),
    @("OPENAI_API_KEY", "summarise, classify and draft will return 503"),
    @("AUTH_USERS", "there is no account to log in with")
)) {
    $key = $pair[0]
    if ($envText -notmatch "(?m)^$key=.+") { Warn "$key is empty in backend\.env - $($pair[1])" }
    else { Ok "$key is set" }
}

# ------------------------------------------------------------- dependencies

if (-not $SkipInstall) {
    Step "Checking Python packages"
    $missing = python -c "
import importlib.util as u
need = {'flask':'Flask','jwt':'PyJWT','flask_cors':'Flask-Cors','dotenv':'python-dotenv','openai':'openai','spacy':'spacy'}
print(','.join(v for k, v in need.items() if u.find_spec(k) is None))
" 2>$null
    if ($missing) {
        Warn "installing missing packages: $missing"
        python -m pip install --quiet -r (Join-Path $root "backend\requirements.txt")
        Ok "packages installed"
    } else {
        Ok "all Python packages present"
    }

    # The spaCy model is a separate download from pip. Without it the grounding
    # layer silently falls back to a weaker capitalisation heuristic.
    $spacyOk = python -c "
import spacy
try:
    spacy.load('en_core_web_sm'); print('yes')
except Exception:
    print('no')
" 2>$null
    if ($spacyOk -ne "yes") {
        Warn "downloading the spaCy model en_core_web_sm (needed for grounding)"
        python -m spacy download en_core_web_sm 2>&1 | Out-Null
        Ok "spaCy model installed"
    } else {
        Ok "spaCy model en_core_web_sm present"
    }

    Step "Checking Node packages"
    if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
        Warn "installing frontend dependencies (this takes a minute the first time)"
        Push-Location (Join-Path $root "frontend")
        npm install --silent
        Pop-Location
        Ok "node_modules installed"
    } else {
        Ok "node_modules present"
    }
} else {
    Step "Skipping dependency check (-SkipInstall)"
}

# -------------------------------------------------------------------- ports

Step "Freeing ports"
if (-not (Stop-Port $BackendPort "old backend")) { Ok "port $BackendPort free" }
if (-not (Stop-Port $FrontendPort "old frontend")) { Ok "port $FrontendPort free" }

# ------------------------------------------------------------------- launch

Step "Starting servers"

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle='DS-25 backend (Flask :$BackendPort)'; Set-Location '$root'; python -m backend.run"
)
Say "    backend window opened"

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle='DS-25 frontend (Vite :$FrontendPort)'; Set-Location '$root\frontend'; npm run dev"
)
Say "    frontend window opened"

Step "Waiting for them to answer"
$backendUp = Wait-ForPort $BackendPort "backend"
$frontendUp = Wait-ForPort $FrontendPort "frontend"

if ($backendUp) {
    try {
        $health = Invoke-RestMethod "http://localhost:$BackendPort/api/healthz" -TimeoutSec 5
        if ($health.status -eq "ok") { Ok "backend health check passed" }
    } catch { Warn "backend is listening but /api/healthz did not answer" }
}

# ------------------------------------------------------------------ finish

Write-Host ""
if ($backendUp -and $frontendUp) {
    Say "  Ready. Opening http://localhost:$FrontendPort" "Green"
    Start-Process "http://localhost:$FrontendPort"
} else {
    Say "  Something did not start. Look at the two windows that opened." "Red"
}

Write-Host ""
Say "  Two windows are now running the servers. To stop everything:" "DarkGray"
Say "    .\start.ps1 -Stop        (or just close both windows)" "DarkGray"
Write-Host ""
