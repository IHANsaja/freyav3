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

# Running from inside a clone? Use it rather than nesting another copy.
$inClone = (Test-Path ".\server.py") -and (Test-Path ".\core") -and (Test-Path ".\requirements.txt")

if ($inClone) {
    $root = (Get-Location).Path
    Write-Ok "Using existing checkout: $root"
} else {
    if (-not $InstallPath) {
        $InstallPath = Join-Path (Get-Location).Path "freyav3"
    }
    if (Test-Path $InstallPath) {
        if (Test-Path (Join-Path $InstallPath "server.py")) {
            Write-Ok "Found existing install at $InstallPath - updating"
            Push-Location $InstallPath
            try {
                git pull --ff-only 2>&1 | Out-Null
                Write-Ok "Pulled latest"
            } catch {
                Write-Warn2 "Could not fast-forward (local changes?) - continuing with what is on disk"
            }
            Pop-Location
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
    }
    $root = (Resolve-Path $InstallPath).Path
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

$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    Write-Ok ".env already exists - leaving it untouched"
} else {
    Write-Host ""
    Write-Host "    Freya needs a Google Gemini API key (the free tier works)." -ForegroundColor White
    Write-Host "    Get one at: https://aistudio.google.com/apikey" -ForegroundColor DarkGray
    Write-Host "    Press Enter to skip and fill it in later." -ForegroundColor DarkGray
    $key = Read-Host "    GEMINI_API_KEY"

    if ([string]::IsNullOrWhiteSpace($key)) {
        $key = "PASTE_YOUR_GEMINI_API_KEY_HERE"
        Write-Warn2 "No key entered - .env written with a placeholder"
    }

    $envBody = @"
# Freya v3 - environment
# Get a key at https://aistudio.google.com/apikey
GEMINI_API_KEY=$key

# Optional: a second key for background agents / memory so heavy text work
# does not consume the live-voice quota. Falls back to GEMINI_API_KEY.
# GEMINI_AGENT_API_KEY=
# GEMINI_MEMORY_API_KEY=
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
Start-Sleep -Seconds 6
Start-Process "http://localhost:3000"
'@
$startBody | Out-File -FilePath $startScript -Encoding utf8
Write-Ok "Created start-freya.ps1"

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
Write-Host ""
Write-Host " Headless CLI instead:  .\venv\Scripts\python.exe main.py" -ForegroundColor DarkGray
Write-Host ""
