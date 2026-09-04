# Intelligent Email Assistant - one-command start.
#
#   .\start.ps1              start everything in THIS window
#   .\start.ps1 -Mail        also run the local SMTP server, so you can email
#                            the assistant and read it in the app
#   .\start.ps1 -MailLan     as -Mail, but accepts mail from other devices on
#                            this network (a phone, a teammate's laptop)
#   .\start.ps1 -SkipInstall skip the dependency check (faster restart)
#   .\start.ps1 -Windows     one separate window per server, for when one of
#                            them is crashing and you want its output alone
#   .\start.ps1 -Stop        stop anything still running
#
# Or double-click start.bat, which calls this and bypasses the PowerShell
# execution policy that otherwise blocks double-clicked .ps1 files.
#
# By default every server runs as a child of this window, with its output
# prefixed and colour-coded so you can tell which one said what. Ctrl+C stops
# all of them. Run it from a terminal you own: servers started inside an agent
# or IDE task session are children of that shell and die when it ends.

param(
    [switch]$Stop,
    [switch]$SkipInstall,
    [switch]$Mail,
    [switch]$MailLan,
    [switch]$Windows
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$BackendPort = 5000
$FrontendPort = 5173
$SmtpPort = 2525
$LogDir = Join-Path $root ".logs"

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
    Fail "$label did not start within $seconds seconds - see its output below"
    return $false
}

# --------------------------------------------------------------------- stop

if ($Stop) {
    Step "Stopping servers"
    $a = Stop-Port $BackendPort "backend"
    $b = Stop-Port $FrontendPort "frontend"
    $c = Stop-Port $SmtpPort "mail server"
    if (-not ($a -or $b -or $c)) { Say "    nothing was running" }
    Write-Host ""
    exit 0
}

Write-Host ""
Say "  Intelligent Email Assistant - FIT3164 DS-25" "White"
Say "  ------------------------------------------" "DarkGray"

# ------------------------------------------------------------ prerequisites

Step "Checking prerequisites"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "Python is not on PATH. Install Python 3.12+ and reopen this terminal."; exit 1
}
Ok "python $((python --version 2>&1) -replace 'Python ')"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "Node.js is not on PATH. Install Node 20+ and reopen this terminal."; exit 1
}
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
    Say "      2. Add an account:  python -m backend.scripts.add_user you@monash.edu yourpassword" "Yellow"
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
need = {'flask':'Flask','jwt':'PyJWT','flask_cors':'Flask-Cors','dotenv':'python-dotenv','openai':'openai','spacy':'spacy','aiosmtpd':'aiosmtpd'}
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
$wantMail = $Mail -or $MailLan
if ($wantMail) {
    if (-not (Stop-Port $SmtpPort "old mail server")) { Ok "port $SmtpPort free" }
}

$mailArgs = if ($MailLan) { @("-m", "backend.mailserver", "--host", "0.0.0.0") }
            else { @("-m", "backend.mailserver") }

# ------------------------------------------------- separate windows (opt in)

if ($Windows) {
    Step "Starting servers in separate windows"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle='DS-25 backend'; Set-Location '$root'; python -m backend.run")
    Say "    backend window opened"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle='DS-25 frontend'; Set-Location '$root\frontend'; npm run dev")
    Say "    frontend window opened"
    if ($wantMail) {
        Start-Process powershell -ArgumentList @("-NoExit", "-Command",
            "`$Host.UI.RawUI.WindowTitle='DS-25 mail'; Set-Location '$root'; python $($mailArgs -join ' ')")
        Say "    mail server window opened"
    }

    Step "Waiting for them to answer"
    $backendUp = Wait-ForPort $BackendPort "backend"
    $frontendUp = Wait-ForPort $FrontendPort "frontend"
    if ($wantMail) { Wait-ForPort $SmtpPort "mail server" | Out-Null }

    Write-Host ""
    if ($backendUp -and $frontendUp) {
        Say "  Ready. Opening http://localhost:$FrontendPort" "Green"
        Start-Process "http://localhost:$FrontendPort"
    }
    Say "  Close the windows, or run .\start.ps1 -Stop, to stop everything." "DarkGray"
    Write-Host ""
    exit 0
}

# ------------------------------------------------------- one window (default)
#
# Each server is a child of this window with its output redirected to a log
# file, which this script reads and reprints with a prefix. The redirection is
# what makes the prefix possible: a child sharing the console writes straight
# past us with no way to label it.

New-Item -ItemType Directory -Force $LogDir | Out-Null

# Ask the children not to emit ANSI colour, which would otherwise land in the
# log files as escape sequences and print here as noise.
$env:NO_COLOR = "1"
$env:FORCE_COLOR = "0"

$services = @()

function Launch($name, $colour, $exe, $argList, $workDir) {
    $out = Join-Path $LogDir "$name.out.log"
    $err = Join-Path $LogDir "$name.err.log"
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    New-Item -ItemType File -Force $out, $err | Out-Null
    $proc = Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $workDir `
        -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    return [pscustomobject]@{
        Name = $name; Colour = $colour; Proc = $proc
        Out = $out; Err = $err; OutAt = 0; ErrAt = 0
    }
}

function Pump($svc) {
    foreach ($stream in @("Out", "Err")) {
        $path = if ($stream -eq "Out") { $svc.Out } else { $svc.Err }
        $at = if ($stream -eq "Out") { $svc.OutAt } else { $svc.ErrAt }
        $lines = @(Get-Content $path -ErrorAction SilentlyContinue)
        if ($lines.Count -gt $at) {
            foreach ($line in $lines[$at..($lines.Count - 1)]) {
                if ($line -and $line.Trim()) {
                    Write-Host ("  [{0,-8}] " -f $svc.Name) -ForegroundColor $svc.Colour -NoNewline
                    Write-Host $line
                }
            }
            if ($stream -eq "Out") { $svc.OutAt = $lines.Count } else { $svc.ErrAt = $lines.Count }
        }
    }
}

Step "Starting servers in this window"

$services += Launch "backend" "Cyan" "python" @("-m", "backend.run") $root
Say "    backend starting"
$services += Launch "frontend" "Magenta" "npm.cmd" @("run", "dev") (Join-Path $root "frontend")
Say "    frontend starting"
if ($wantMail) {
    $services += Launch "mail" "Yellow" "python" $mailArgs $root
    Say "    mail server starting"
}

try {
    Step "Waiting for them to answer"
    $backendUp = Wait-ForPort $BackendPort "backend"
    $frontendUp = Wait-ForPort $FrontendPort "frontend"
    if ($wantMail) { Wait-ForPort $SmtpPort "mail server" | Out-Null }

    if ($backendUp) {
        try {
            $health = Invoke-RestMethod "http://localhost:$BackendPort/api/healthz" -TimeoutSec 5
            if ($health.status -eq "ok") { Ok "backend health check passed" }
        } catch { Warn "backend is listening but /api/healthz did not answer" }
    }

    Write-Host ""
    if ($backendUp -and $frontendUp) {
        Say "  Ready. Opening http://localhost:$FrontendPort" "Green"
        Start-Process "http://localhost:$FrontendPort"
    } else {
        Say "  Something did not start. Its output appears below." "Red"
    }

    if ($wantMail) {
        Write-Host ""
        Say "  Mail server on port $SmtpPort. From another terminal:" "DarkGray"
        Say "    python tools/send_test_email.py" "DarkGray"
        if ($MailLan) {
            $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                   Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
                   Select-Object -First 1).IPAddress
            if ($ip) { Say "  From another device: SMTP $ip port $SmtpPort, no auth, no TLS." "DarkGray" }
        }
    }

    Write-Host ""
    Say "  Server output follows. Press Ctrl+C to stop everything." "DarkGray"
    Say "  ----------------------------------------------------------" "DarkGray"
    Write-Host ""

    while ($true) {
        foreach ($svc in $services) { Pump $svc }

        $dead = @($services | Where-Object { $_.Proc.HasExited })
        if ($dead.Count -gt 0) {
            Write-Host ""
            foreach ($d in $dead) { Fail "$($d.Name) exited (code $($d.Proc.ExitCode))" }
            Say "  Shutting the rest down." "Red"
            break
        }
        Start-Sleep -Milliseconds 300
    }
}
finally {
    # Runs on Ctrl+C as well as on a crash, so nothing is left holding a port.
    Write-Host ""
    Step "Stopping"
    foreach ($svc in $services) {
        if (-not $svc.Proc.HasExited) {
            try { Stop-Process -Id $svc.Proc.Id -Force -ErrorAction Stop; Ok "stopped $($svc.Name)" }
            catch { Warn "could not stop $($svc.Name)" }
        }
    }
    # npm spawns vite as a grandchild, which outlives its parent being killed.
    Stop-Port $FrontendPort "frontend child" | Out-Null
    Remove-Item Env:\NO_COLOR, Env:\FORCE_COLOR -ErrorAction SilentlyContinue
    Write-Host ""
}
