<#
.SYNOPSIS
    One-command installer for Freya v3 - the local Gemini Live voice assistant.

.DESCRIPTION
    Verifies prerequisites, fetches the repository, builds the Python virtual
    environment and the Next.js dashboard, and scaffolds configuration.

    Run it straight from the web:

        irm https://raw.githubusercontent.com/IHANsaja/freyav3/main/install.ps1 | iex

    Or, from an existing clone:

        .\install.ps1

.PARAMETER InstallPath
    Where to clone Freya. Defaults to .\freyav3 in the current directory.
    Ignored when the script is run from inside an existing clone.

.PARAMETER SkipBrowser
    Skip the Playwright Chromium download (~150 MB). The browser_task tool
    will not work until you later run: playwright install chromium

.PARAMETER SkipFrontend
    Skip npm install for the dashboard. Use for a headless/CLI-only setup.

.NOTES
    Windows only - Freya drives the Windows accessibility API, WASAPI audio and
    the Win32 window manager.

    This file is deliberately ASCII-only: Windows PowerShell 5.1 reads a
    BOM-less .ps1 using the system ANSI codepage, so non-ASCII characters
    (box drawing, em dashes, arrows) corrupt the parse on some machines.
#>
[CmdletBinding()]
param(
    [string]$InstallPath = "",
    [switch]$SkipBrowser,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/IHANsaja/freyav3.git"

# -- Output helpers --------------------------------------------------------
function Write-Step  ($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok    ($m) { Write-Host "    [ok] $m" -ForegroundColor Green }
function Write-Warn2 ($m) { Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Write-Fail  ($m) { Write-Host "    [x]  $m" -ForegroundColor Red }

function Test-Command ($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host ""
Write-Host "  F R E Y A   v3" -ForegroundColor Cyan
Write-Host "  local voice assistant + agent dashboard" -ForegroundColor DarkGray
Write-Host ""

# -- 0. Platform -----------------------------------------------------------
if ($env:OS -ne "Windows_NT") {
    Write-Fail "Freya is Windows-only (accessibility API, WASAPI audio, Win32 windows)."
    return
}

# -- 1. Prerequisites ------------------------------------------------------
Write-Step "Checking prerequisites"

$missing = @()

# Python 3.10+
$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    if (Test-Command $candidate) {
        try {
            $v = & $candidate --version 2>&1
            if ($v -match "Python (\d+)\.(\d+)") {
                $maj = [int]$Matches[1]
                $min = [int]$Matches[2]
                if ($maj -eq 3 -and $min -ge 10) {
                    $pythonExe = $candidate
                    Write-Ok "Python $maj.$min ($candidate)"
                    break
                }
            }
        } catch { }
    }
}
if (-not $pythonExe) {
    $missing += "Python 3.10+  ->  https://www.python.org/downloads/"
}

# Node 18+
if (Test-Command "node") {
    $nodeV = (& node --version) -replace "v", ""
    $nodeMajor = [int]($nodeV -split "\.")[0]
    if ($nodeMajor -ge 18) {
        Write-Ok "Node.js $nodeV"
    } else {
        $missing += "Node.js 18+ (found $nodeV)  ->  https://nodejs.org/"
    }
} elseif (-not $SkipFrontend) {
    $missing += "Node.js 18+  ->  https://nodejs.org/  (or re-run with -SkipFrontend)"
}

# git
if (Test-Command "git") {
    Write-Ok "git"
} else {
    $missing += "git  ->  https://git-scm.com/download/win"
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Fail "Missing prerequisites:"
    $missing | ForEach-Object { Write-Host "         - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "    Install them, then re-run this script." -ForegroundColor Yellow
    Write-Host ""
    return
}

# -- 2. Get the source -----------------------------------------------------
Write-Step "Locating Freya"

# Runs git against one checkout. safe.directory stops git refusing a folder
# another account owns (an install made from an admin shell), and a local
# Continue keeps git's stderr from becoming a terminating error in PS 5.1.
# Check $LASTEXITCODE afterwards.
function Invoke-Git ($repo) {
    $ErrorActionPreference = "Continue"
    & git -c "safe.directory=$($repo -replace '\\', '/')" -C $repo @args 2>&1 | ForEach-Object { "$_" }
}

function Test-InWindowsDir ($path) {
    return $path.TrimEnd('\').StartsWith($env:windir, [StringComparison]::OrdinalIgnoreCase)
}

# Fast-forwards an existing install to the latest commit on GitHub and says
# plainly when that did not happen - it used to print "Pulled latest" either way.
function Update-Checkout ($repo) {
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
        Write-Warn2 "Freya looks like it is running. Close her windows first if the update fails."
    }
    $before = Invoke-Git $repo rev-parse --short HEAD
    # npm install rewrites package-lock.json; that churn must not block a pull.
    Invoke-Git $repo checkout -- freya-ui/package-lock.json | Out-Null
    $out = Invoke-Git $repo pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Could not update from GitHub - still on $($before):"
        $out | ForEach-Object { Write-Host "         $_" -ForegroundColor Red }
        Write-Warn2 "Usually a local edit to one of Freya's own files. See them with:"
        Write-Warn2 "  git -C `"$repo`" status"
        return
    }
    $after = Invoke-Git $repo rev-parse --short HEAD
    if ($before -eq $after) {
        Write-Ok "Already on the latest version ($after)"
    } else {
        Write-Ok "Updated $before -> $after"
    }
}

# Admin PowerShell opens in C:\Windows\System32, so running the one-liner there
# used to clone Freya into the Windows folder, which git then refused to update.
$legacyRoot = Join-Path $env:windir "System32\freyav3"

# Brings the personal files (keys, settings, memories, custom skills) of an old
# System32 install into a fresh clone. Only files git does not track are copied,
# minus what gets rebuilt anyway; the old folder is left for the user to delete.
function Copy-LegacyData ($from, $to) {
    $rebuilt = '^(venv|freya-ui/node_modules|freya-ui/\.next|freya-ui/next-env\.d\.ts|start-freya\.ps1|update-freya\.ps1)(/|$)|(^|/)__pycache__/'
    $copied = 0
    foreach ($rel in (Invoke-Git $from ls-files --others --directory)) {
        if ($LASTEXITCODE -ne 0 -or $rel -match $rebuilt) { continue }
        $src = Join-Path $from $rel.TrimEnd('/')
        $dst = Join-Path $to $rel.TrimEnd('/')
        if (Test-Path $dst) { continue }
        New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
        Copy-Item $src $dst -Recurse
        $copied++
    }
    Write-Ok "Brought over $copied item(s) from the old install: .env, settings, memories"
    Write-Warn2 "The old copy is still in $from - delete it from an admin shell once Freya works."
}

# Running from inside a clone? Use it rather than nesting another copy.
$inClone = (Test-Path ".\server.py") -and (Test-Path ".\core") -and (Test-Path ".\requirements.txt")

if ($inClone) {
    $root = (Get-Location).Path
    Write-Ok "Using existing checkout: $root"
    Update-Checkout $root
} else {
    if (-not $InstallPath) {
        $base = (Get-Location).Path
        if (Test-InWindowsDir $base) {
            $base = $HOME
            Write-Warn2 "Not installing inside the Windows folder - using $base instead"
        }
        $InstallPath = Join-Path $base "freyav3"
    }
    if (Test-Path $InstallPath) {
        if (Test-Path (Join-Path $InstallPath "server.py")) {
            Write-Ok "Found existing install at $InstallPath - updating"
            Update-Checkout (Resolve-Path $InstallPath).Path
        } else {
            Write-Fail "$InstallPath exists but does not look like Freya. Move it or pass -InstallPath."
            return
        }
    } else {
        Write-Host "    Cloning $RepoUrl"
        git clone --depth 1 $RepoUrl $InstallPath
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "git clone failed."
            return
        }
        Write-Ok "Cloned to $InstallPath"
        $newRoot = (Resolve-Path $InstallPath).Path
        if ((Test-Path (Join-Path $legacyRoot "server.py")) -and $newRoot -ne $legacyRoot) {
            Write-Ok "Found an older install in $legacyRoot - moving your data over"
            Copy-LegacyData $legacyRoot $newRoot
        }
    }
    $root = (Resolve-Path $InstallPath).Path
}

if (Test-InWindowsDir $root) {
    Write-Warn2 "Freya is inside the Windows folder ($root), where updates break."
    Write-Warn2 "Run the installer from a normal folder (e.g. cd ~) to move her out."
}

Set-Location $root

# -- 3. Python environment -------------------------------------------------
Write-Step "Building the Python environment"

$venvPython = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $pythonExe -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Could not create the virtual environment."
        return
    }
    Write-Ok "Created venv"
} else {
    Write-Ok "venv already present"
}

& $venvPython -m pip install --upgrade pip --quiet
Write-Host "    Installing Python dependencies (this takes a few minutes)..."
& $venvPython -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "Some Python packages failed."
    Write-Warn2 "PyAudio is the usual culprit - it needs C++ Build Tools:"
    Write-Warn2 "  https://visualstudio.microsoft.com/visual-cpp-build-tools/"
} else {
    Write-Ok "Python dependencies installed"
}

if (-not $SkipBrowser) {
    Write-Host "    Installing Chromium for browser automation..."
    & $venvPython -m playwright install chromium 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Chromium installed"
    } else {
        Write-Warn2 "Chromium install failed - 'browser_task' will be unavailable"
    }
}

# -- 4. Dashboard ----------------------------------------------------------
if (-not $SkipFrontend) {
    Write-Step "Building the dashboard"
    Push-Location (Join-Path $root "freya-ui")
    Write-Host "    Running npm install..."
    npm install --no-audit --no-fund --loglevel=error
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Dashboard dependencies installed"
    } else {
        Write-Warn2 "npm install reported problems - check the output above"
    }
    Pop-Location
}

# -- 5. Configuration ------------------------------------------------------
Write-Step "Configuring"

$placeholderKey = "PASTE_YOUR_GEMINI_API_KEY_HERE"

# Asks Google whether a key works, so a bad paste is caught here instead of as
# "1008 invalid authentication credentials" five times over at first launch.
# Returns "ok", "rejected", or "unknown" (offline / Google unreachable).
function Test-GeminiKey ($k) {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-RestMethod -Uri "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1" `
            -Headers @{ "x-goog-api-key" = $k } -TimeoutSec 15 | Out-Null
        return "ok"
    } catch {
        $status = 0
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($status -in 400, 401, 403) { return "rejected" }
        return "unknown"
    }
}

# Prompts until Google accepts the key, or the user skips. Returns the key or $null.
function Read-GeminiKey {
    Write-Host ""
    Write-Host "    Freya needs a Google Gemini API key (the free tier works)." -ForegroundColor White
    Write-Host "    Get one at: https://aistudio.google.com/apikey" -ForegroundColor DarkGray
    Write-Host "    Press Enter to skip and fill it in later." -ForegroundColor DarkGray
    for ($try = 1; $try -le 3; $try++) {
        $k = Read-Host "    GEMINI_API_KEY"
        if ([string]::IsNullOrWhiteSpace($k)) { return $null }
        # Pasted keys often carry spaces or quotes along.
        $k = $k.Trim().Trim('"', "'").Trim()
        switch (Test-GeminiKey $k) {
            "ok"      { Write-Ok "Google accepted the key"; return $k }
            "unknown" { Write-Warn2 "Could not reach Google to check the key - saving it anyway"; return $k }
            default {
                Write-Fail "Google rejected that key (invalid authentication credentials)."
                Write-Warn2 "Copy the whole key again from https://aistudio.google.com/apikey,"
                Write-Warn2 "or create a new one there. Press Enter to skip."
            }
        }
    }
    Write-Warn2 "Still rejected - skipping. Put a working key in .env before starting Freya."
    return $null
}

$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    Write-Ok ".env already exists - leaving it untouched"
    # Re-running the installer is how most people try to fix a bad key, so
    # check the saved one and offer to replace it if Google refuses it.
    $envText = Get-Content $envPath -Raw
    if ($envText -match "(?m)^\s*GEMINI_API_KEY\s*=\s*(.*?)\s*$") {
        $savedKey = $Matches[1].Trim().Trim('"', "'").Trim()
        if ($savedKey -and $savedKey -ne $placeholderKey -and (Test-GeminiKey $savedKey) -eq "rejected") {
            Write-Fail "Google rejects the GEMINI_API_KEY saved in .env."
            $newKey = Read-GeminiKey
            if ($newKey) {
                $envText = [regex]::Replace($envText, "(?m)^\s*GEMINI_API_KEY\s*=.*$", "GEMINI_API_KEY=$newKey")
                $envText | Out-File -FilePath $envPath -Encoding utf8 -NoNewline
                Write-Ok "Updated GEMINI_API_KEY in .env"
            }
        }
    }
} else {
    $key = Read-GeminiKey
    if (-not $key) {
        $key = $placeholderKey
        Write-Warn2 "No key entered - .env written with a placeholder"
    }

    # Jev (TypeSafe System One) is early-access. The key alone switches it on:
    # with it Freya makes fast routing/triage decisions via Jev, without it she
    # runs on Gemini only - nothing else to configure either way.
    Write-Host ""
    Write-Host "    Optional: Jev (TypeSafe) API key - early-access users only." -ForegroundColor White
    Write-Host "    Press Enter to skip; Freya then runs on Gemini only." -ForegroundColor DarkGray
    $jevKey = Read-Host "    TYPESAFE_API_KEY"
    if ([string]::IsNullOrWhiteSpace($jevKey)) {
        $jevLine = "# TYPESAFE_API_KEY="
        Write-Ok "No Jev key - Freya will use Gemini only"
    } else {
        $jevLine = "TYPESAFE_API_KEY=$($jevKey.Trim())"
        Write-Ok "Jev key saved - Freya will use Jev with Gemini as fallback"
    }

    $envBody = @"
# Freya v3 - environment
# Get a key at https://aistudio.google.com/apikey
GEMINI_API_KEY=$key

# Optional: a second key for background agents / memory so heavy text work
# does not consume the live-voice quota. Falls back to GEMINI_API_KEY.
# GEMINI_AGENT_API_KEY=
# GEMINI_MEMORY_API_KEY=

# Optional, early access: Jev (TypeSafe System One). Setting this key turns Jev
# on; leave it unset and Freya runs on Gemini only.
$jevLine
"@
    $envBody | Out-File -FilePath $envPath -Encoding utf8
    Write-Ok "Wrote .env"
}

# Identity. memory\MEMORY.md is the ONLY place Freya takes your name from
# (core\user_identity.py) - without it she never uses a name at all.
$idExample = Join-Path $root "memory\MEMORY.example.md"
$idFile    = Join-Path $root "memory\MEMORY.md"
if (-not (Test-Path $idFile)) {
    Write-Host ""
    Write-Host "    What should Freya call you? (Enter to skip)" -ForegroundColor White
    $userName = Read-Host "    Your name"

    if ([string]::IsNullOrWhiteSpace($userName)) {
        if (Test-Path $idExample) {
            Copy-Item $idExample $idFile
            Write-Warn2 "No name given - edit memory\MEMORY.md to add one"
        }
    } else {
        $userName = $userName.Trim()
        $idBody = "# Freya Memory - $userName`r`n`r`n## Personal`r`n- Name: $userName`r`n"
        $idBody | Out-File -FilePath $idFile -Encoding utf8
        Write-Ok "Wrote memory\MEMORY.md - Freya will call you $userName"
    }
}

# -- 6. Launch helper ------------------------------------------------------
$startScript = Join-Path $root "start-freya.ps1"
$startBody = @'
# Starts both halves of Freya: the FastAPI backend and the Next.js dashboard.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root'; .\venv\Scripts\python.exe server.py"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\freya-ui'; npm run dev"
# The dashboard's first compile can take 15+ seconds; open it once it answers
# instead of after a fixed delay that often landed on an error page.
Write-Host "Waiting for the dashboard to come up..."
for ($i = 0; $i -lt 90; $i++) {
    try {
        Invoke-WebRequest "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 2 | Out-Null
        break
    } catch { Start-Sleep -Seconds 1 }
}
Start-Process "http://localhost:3000"
'@
$startBody | Out-File -FilePath $startScript -Encoding utf8
Write-Ok "Created start-freya.ps1"

# Always runs the newest installer from GitHub against this folder, so update
# logic fixed upstream reaches old installs too.
$updateScript = Join-Path $root "update-freya.ps1"
$updateBody = @'
# Updates Freya to the latest version on GitHub: code, Python packages and dashboard.
# Your .env, settings and memories are kept. Restart Freya afterwards.
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Invoke-Expression (Invoke-RestMethod "https://raw.githubusercontent.com/IHANsaja/freyav3/main/install.ps1")
'@
$updateBody | Out-File -FilePath $updateScript -Encoding utf8
Write-Ok "Created update-freya.ps1"

# -- Done ------------------------------------------------------------------
Write-Host ""
Write-Host "--------------------------------------------------------" -ForegroundColor DarkCyan
Write-Host " Freya is installed." -ForegroundColor Green
Write-Host "--------------------------------------------------------" -ForegroundColor DarkCyan
Write-Host ""
Write-Host " Location:  $root" -ForegroundColor Gray
Write-Host ""

if ((Get-Content $envPath -Raw) -match "PASTE_YOUR_GEMINI_API_KEY_HERE") {
    Write-Host " 1. Add your API key to .env  (GEMINI_API_KEY=...)" -ForegroundColor Yellow
    Write-Host " 2. Start everything:  .\start-freya.ps1" -ForegroundColor White
} else {
    Write-Host " Start everything:  .\start-freya.ps1" -ForegroundColor White
    Write-Host " Then open:         http://localhost:3000" -ForegroundColor Gray
}
if ((Get-Content $envPath -Raw) -match "(?m)^\s*TYPESAFE_API_KEY=\S") {
    Write-Host " Jev: on (TYPESAFE_API_KEY set)" -ForegroundColor DarkGray
} else {
    Write-Host " Jev: off - Gemini only (add TYPESAFE_API_KEY to .env if you have early access)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host " Headless CLI instead:  .\venv\Scripts\python.exe main.py" -ForegroundColor DarkGray
Write-Host " Update later:          .\update-freya.ps1" -ForegroundColor DarkGray
Write-Host ""
