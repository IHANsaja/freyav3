<#
.SYNOPSIS
    One-command installer for Freya v3 - the local Gemini Live voice assistant.

.DESCRIPTION
    Installs any missing prerequisites (Python, Node.js, git) with winget,
    fetches the repository, builds the Python virtual environment and the
    Next.js dashboard, and scaffolds configuration.

    Run it straight from the web:

        irm https://raw.githubusercontent.com/IHANsaja/freyav3/main/install.ps1 | iex

    Or, from an existing clone:

        .\install.ps1

.PARAMETER InstallPath
    Where to put Freya. Defaults to the install the shell is already inside,
    else %USERPROFILE%\freyav3 - the same place whichever folder the
    command is run from.

.PARAMETER SkipBrowser
    Skip the Playwright Chromium download (~150 MB). The browser_task tool
    will not work until you later run: playwright install chromium

.PARAMETER SkipFrontend
    Skip npm install for the dashboard. Use for a headless/CLI-only setup.

.PARAMETER NoStart
    Install or update only; do not start Freya at the end.

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
    [switch]$SkipFrontend,
    [switch]$NoStart
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

# Returns the command or full path of a Python 3.10+, or $null. The Microsoft
# Store "python" alias only prints an install hint, so it never matches.
function Find-Python {
    $candidates = @("python", "python3", "py")
    # A fresh install may not be on this session's PATH yet; look where the
    # python.org / winget installer puts it, newest first.
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Name -replace "\D", "") } -Descending |
        ForEach-Object { $_.FullName }
    foreach ($candidate in $candidates) {
        if (-not (Test-Command $candidate)) { continue }
        try {
            $v = & $candidate --version 2>&1
            if ("$v" -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) {
                return $candidate
            }
        } catch { }
    }
    return $null
}

# Node.js major version, or 0 when it is missing.
function Get-NodeMajor {
    if (-not (Test-Command "node")) { return 0 }
    try { return [int](((& node --version) -replace "v", "") -split "\.")[0] } catch { return 0 }
}

# Checks all three and returns what is still missing, as winget package ids
# mapped to a readable name.
function Get-MissingPrereqs {
    $need = [ordered]@{}
    if (-not (Find-Python)) { $need["Python.Python.3.12"] = "Python 3.12" }
    if (-not $SkipFrontend -and (Get-NodeMajor) -lt 18) { $need["OpenJS.NodeJS.LTS"] = "Node.js LTS" }
    if (-not (Test-Command "git")) { $need["Git.Git"] = "git" }
    return $need
}

# Installers add themselves to the machine/user PATH, not to this session's.
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

$missing = Get-MissingPrereqs
if ($missing.Count -gt 0) {
    if (Test-Command "winget") {
        Write-Host "    Installing what is missing: $($missing.Values -join ', ')" -ForegroundColor White
        Write-Host "    Windows may ask for permission once per program - click Yes." -ForegroundColor DarkGray
        foreach ($id in @($missing.Keys)) {
            Write-Host "    Installing $($missing[$id])..."
            # Keep a failed install from stopping the script: the re-check
            # below reports whatever is still missing.
            $ErrorActionPreference = "Continue"
            winget install --id $id --exact --silent --source winget `
                --accept-package-agreements --accept-source-agreements | Out-Host
            $ErrorActionPreference = "Stop"
        }
        Update-SessionPath
        $missing = Get-MissingPrereqs
    } else {
        Write-Warn2 "winget (App Installer) is not available, so prerequisites cannot be installed automatically."
    }
}

if ($missing.Count -gt 0) {
    $links = @{
        "Python.Python.3.12" = "https://www.python.org/downloads/  (tick 'Add python.exe to PATH')"
        "OpenJS.NodeJS.LTS"  = "https://nodejs.org/  (or re-run with -SkipFrontend)"
        "Git.Git"            = "https://git-scm.com/download/win"
    }
    Write-Host ""
    Write-Fail "Still missing:"
    foreach ($id in $missing.Keys) {
        Write-Host "         - $($missing[$id])  ->  $($links[$id])" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "    Install them, then open a NEW PowerShell window and re-run this command." -ForegroundColor Yellow
    Write-Host ""
    return
}

$pythonExe = Find-Python
Write-Ok "Python ($(& $pythonExe --version 2>&1))"
if (-not $SkipFrontend) { Write-Ok "Node.js $(& node --version)" }
Write-Ok "git"

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

# Copies the personal files (keys, settings, memories, custom skills) of one
# checkout into another. Only files git does not track are copied, minus what
# gets rebuilt anyway, and nothing already present in $to is overwritten.
function Copy-PersonalData ($from, $to) {
    $rebuilt = '^(venv|freya-ui/node_modules|freya-ui/\.next|freya-ui/next-env\.d\.ts|(start|update)-freya\.(ps1|cmd))(/|$)|(^|/)__pycache__/'
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
    return $copied
}

function Test-Checkout ($dir) {
    return (Test-Path (Join-Path $dir "server.py")) -and (Test-Path (Join-Path $dir "core")) -and
           (Test-Path (Join-Path $dir "requirements.txt"))
}

# The outermost checkout containing $dir, or $null. Outermost, because an
# interrupted run could leave the shell inside a copy nested in another one.
function Find-CheckoutRoot ($dir) {
    $found = $null
    while ($dir) {
        if (Test-Checkout $dir) { $found = $dir }
        $dir = Split-Path -Parent $dir
    }
    return $found
}

# Clones with a few retries: a dropped connection mid-download ("curl 56",
# "early EOF") otherwise ends the whole install.
function Invoke-Clone ($path) {
    for ($try = 1; $try -le 3; $try++) {
        Write-Host "    Downloading Freya (about 60 MB)..."
        $ErrorActionPreference = "Continue"
        git -c http.version=HTTP/1.1 clone --depth 1 $RepoUrl $path | Out-Host
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -eq 0) { return $true }
        if (Test-Path $path) { Remove-Item $path -Recurse -Force }
        if ($try -lt 3) {
            Write-Warn2 "The download was interrupted - trying again ($($try + 1)/3)..."
            Start-Sleep -Seconds (5 * $try)
        }
    }
    return $false
}

# One place, whichever folder the command is run from: the checkout the shell
# is already in (outermost), else %USERPROFILE%\freyav3. Never the Windows folder.
$here = Find-CheckoutRoot (Get-Location).Path
if ($InstallPath) {
    $root = [IO.Path]::GetFullPath($InstallPath)
} elseif ($here -and -not (Test-InWindowsDir $here)) {
    $root = $here
} else {
    $root = Join-Path $HOME "freyav3"
}

if (Test-Checkout $root) {
    Write-Ok "Found Freya in $root - updating"
    Update-Checkout $root
} elseif ((Test-Path $root) -and (Get-ChildItem $root -Force | Select-Object -First 1)) {
    Write-Fail "$root exists but does not look like Freya. Move it or pass -InstallPath."
    return
} else {
    if (-not (Invoke-Clone $root)) {
        Write-Fail "Could not download Freya - check the internet connection and run the command again."
        return
    }
    Write-Ok "Downloaded to $root"
    if ((Test-Path (Join-Path $legacyRoot "server.py")) -and $root -ne $legacyRoot) {
        $n = Copy-PersonalData $legacyRoot $root
        Write-Ok "Brought over $n item(s) from the old install in $legacyRoot"
        Write-Warn2 "The old copy is still there - delete it from an admin shell once Freya works."
    }
}

# Out of any folder about to be removed, and where the rest of the steps run.
Set-Location $root

# A copy that an interrupted run cloned inside this one (e.g. freya-ui\freyav3).
# Keep anything personal from it, then remove it: it would otherwise be picked
# up by the dashboard build and by the next run.
foreach ($rel in (Invoke-Git $root ls-files --others --directory)) {
    $nested = Join-Path $root $rel.TrimEnd('/')
    if ($rel -match '(^|/)(node_modules|venv|\.next)/' -or -not (Test-Path $nested -PathType Container)) { continue }
    if (-not (Test-Checkout $nested)) { continue }
    $n = Copy-PersonalData $nested $root
    Remove-Item $nested -Recurse -Force
    Write-Ok "Removed a duplicate copy at $nested (kept $n personal item(s))"
}

if (Test-InWindowsDir $root) {
    Write-Warn2 "Freya is inside the Windows folder ($root), where updates break."
}

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
    Write-Host "    Running npm install..."
    # npm.cmd, not npm: PowerShell would pick npm.ps1, which Windows' default
    # execution policy refuses to run ("running scripts is disabled").
    # try/finally: this script runs in the caller's shell (irm | iex), so an
    # error here used to leave the user sitting in freya-ui.
    Push-Location (Join-Path $root "freya-ui")
    try {
        & npm.cmd install --no-audit --no-fund --loglevel=error
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Dashboard dependencies installed"
        } else {
            Write-Warn2 "npm install reported problems - check the output above"
        }
    } finally {
        Pop-Location
    }
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
    # Re-running the installer is how people add a skipped key or fix a bad
    # one, so ask again when the saved key is missing, the placeholder, or
    # refused by Google.
    $envText = Get-Content $envPath -Raw
    $savedKey = ""
    if ($envText -match "(?m)^\s*GEMINI_API_KEY\s*=\s*(.*?)\s*$") {
        $savedKey = $Matches[1].Trim().Trim('"', "'").Trim()
    }
    $askAgain = $false
    if (-not $savedKey -or $savedKey -eq $placeholderKey) {
        Write-Warn2 "No Gemini API key saved yet."
        $askAgain = $true
    } elseif ((Test-GeminiKey $savedKey) -eq "rejected") {
        Write-Fail "Google rejects the GEMINI_API_KEY saved in .env."
        $askAgain = $true
    }
    if ($askAgain) {
        $newKey = Read-GeminiKey
        if ($newKey) {
            if ($envText -match "(?m)^\s*GEMINI_API_KEY\s*=") {
                $envText = [regex]::Replace($envText, "(?m)^\s*GEMINI_API_KEY\s*=.*$", "GEMINI_API_KEY=$newKey")
            } else {
                $envText = "GEMINI_API_KEY=$newKey`r`n" + $envText
            }
            $envText | Out-File -FilePath $envPath -Encoding utf8 -NoNewline
            Write-Ok "Saved GEMINI_API_KEY in .env"
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
Start-Process powershell -ArgumentList "-NoExit","-ExecutionPolicy","Bypass","-Command","cd '$root'; .\venv\Scripts\python.exe server.py"
Start-Process powershell -ArgumentList "-NoExit","-ExecutionPolicy","Bypass","-Command","cd '$root\freya-ui'; npm.cmd run dev"
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

# Windows' default execution policy refuses to run .ps1 files, so each script
# gets a .cmd twin that runs it with the policy bypassed for that one process
# only - nothing on the system changes. Double-click them, or run them from
# any shell. ASCII + CRLF so cmd.exe reads them on every codepage.
foreach ($name in "start-freya", "update-freya") {
    $cmdBody = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0$name.ps1`"`r`n"
    [IO.File]::WriteAllText((Join-Path $root "$name.cmd"), $cmdBody, [Text.Encoding]::ASCII)
}
Write-Ok "Created start-freya.cmd and update-freya.cmd"

# -- Done ------------------------------------------------------------------
Write-Host ""
Write-Host "--------------------------------------------------------" -ForegroundColor DarkCyan
Write-Host " Freya is installed." -ForegroundColor Green
Write-Host "--------------------------------------------------------" -ForegroundColor DarkCyan
Write-Host ""
Write-Host " Location:  $root" -ForegroundColor Gray
Write-Host ""

# Starting without a working key would only end in "invalid credentials".
$needsKey = $true
if ((Get-Content $envPath -Raw) -match "(?m)^\s*GEMINI_API_KEY\s*=\s*(.*?)\s*$") {
    $finalKey = $Matches[1].Trim().Trim('"', "'").Trim()
    $needsKey = (-not $finalKey) -or $finalKey -eq $placeholderKey -or (Test-GeminiKey $finalKey) -eq "rejected"
}
$alreadyRunning = [bool](Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
if ($needsKey) {
    Write-Host " Freya needs a working Gemini API key before she can start." -ForegroundColor Yellow
    Write-Host " Get one at https://aistudio.google.com/apikey and run the same command" -ForegroundColor Yellow
    Write-Host " again - it will ask for the key and then start her." -ForegroundColor Yellow
} elseif ($alreadyRunning) {
    Write-Host " Freya is already running - close her windows and double-click" -ForegroundColor Yellow
    Write-Host " start-freya.cmd to use this version." -ForegroundColor Yellow
} elseif ($NoStart) {
    Write-Host " Start everything:  .\start-freya.cmd  (or double-click it)" -ForegroundColor White
} else {
    # The one command ends with Freya running: backend, dashboard, browser.
    Write-Host " Starting Freya - the dashboard opens in your browser when it is ready." -ForegroundColor Green
    Write-Host " Next time, double-click start-freya.cmd in the folder above." -ForegroundColor Gray
    Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$startScript`"" -WindowStyle Minimized
}
if ((Get-Content $envPath -Raw) -match "(?m)^\s*TYPESAFE_API_KEY=\S") {
    Write-Host " Jev: on (TYPESAFE_API_KEY set)" -ForegroundColor DarkGray
} else {
    Write-Host " Jev: off - Gemini only (add TYPESAFE_API_KEY to .env if you have early access)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host " Headless CLI instead:  .\venv\Scripts\python.exe main.py" -ForegroundColor DarkGray
Write-Host " Update later:          .\update-freya.cmd" -ForegroundColor DarkGray
Write-Host ""
