# Lapicero installer for Windows 10/11.
# Checks every dependency and offers to install what is missing:
#   - Python 3.10+ (via winget)            - required
#   - Lapicero's virtual environment       - required (.venv + requirements.txt)
#   - Claude Code (official native installer or winget) - needed for Ask Claude
#   - Git for Windows (via winget)         - optional, recommended by the Claude Code docs
#   - Desktop / Start menu shortcuts       - optional (create_shortcut.ps1)
#   - The lapicero MCP server in Claude Code - optional
#
# Run from this folder (or double-click install.cmd):
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
# Options:
#   -Yes        answer yes to every question (unattended install)
#   -CheckOnly  only report what is installed; change nothing

param(
    [switch]$Yes,
    [switch]$CheckOnly
)

# Not "Stop": Windows PowerShell 5.1 turns any stderr line from a native program
# (claude, pip, winget) into a terminating error. Native results are checked with
# $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$minPython = [version]"3.10"
$missingRequired = @()

function Write-Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  [ok] $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [!]  $text" -ForegroundColor Yellow }
function Write-Bad($text) { Write-Host "  [x]  $text" -ForegroundColor Red }

function Confirm-Action($question) {
    if ($CheckOnly) { return $false }
    if ($Yes) { Write-Host "  $question [Y/n] y (-Yes)"; return $true }
    $answer = Read-Host "  $question [Y/n]"
    return ($answer -eq "" -or $answer -match "^(y|yes|s|si)$")
}

function Test-Command($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# Re-read PATH from the registry so tools installed by this script are found
# without opening a new terminal.
function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    $claudeBin = Join-Path $env:USERPROFILE ".local\bin"
    if ((Test-Path $claudeBin) -and ($env:Path -notlike "*$claudeBin*")) { $env:Path = "$env:Path;$claudeBin" }
}

function Install-WithWinget($id, $label) {
    if (-not (Test-Command "winget")) {
        Write-Bad "winget is not available. Install $label manually, then run this installer again."
        return $false
    }
    winget install --id $id --exact --source winget --accept-package-agreements --accept-source-agreements
    Update-SessionPath
    return ($LASTEXITCODE -eq 0)
}

# Returns @{ Command = <array>; Version = <version> } for the first Python 3.10+ found, or $null.
function Find-Python {
    $candidates = @()
    if (Test-Command "py") { $candidates += ,@("py", "-3") }
    if (Test-Command "python") { $candidates += ,@("python") }
    foreach ($candidate in $candidates) {
        try {
            $exe = $candidate[0]
            $rest = @($candidate | Select-Object -Skip 1)
            $out = & $exe @rest -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $version = [version]($out | Select-Object -First 1)
                if ($version -ge $minPython) { return @{ Command = $candidate; Version = $version } }
            }
        } catch { }
    }
    return $null
}

function Get-ClaudeVersion {
    if (-not (Test-Command "claude")) { return $null }
    try {
        $out = & claude --version 2>$null
        if ($LASTEXITCODE -eq 0) { return ($out | Select-Object -First 1) }
    } catch { }
    return $null
}

Write-Host "Lapicero installer" -ForegroundColor White
if ($CheckOnly) { Write-Host "(check only: nothing will be changed)" }
Update-SessionPath

# --- 1. System ---------------------------------------------------------------
Write-Step "System"
$build = [Environment]::OSVersion.Version.Build
if ($build -ge 17763) { Write-Ok "Windows build $build (Claude Code needs Windows 10 1809+ / build 17763+)" }
else { Write-Warn "Windows build $build is older than 1809 (17763). Claude Code will not run here." }
$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -in @("AMD64", "ARM64")) { Write-Ok "Processor: $arch" } else { Write-Warn "Processor $arch is not x64/ARM64." }

# --- 2. Python ---------------------------------------------------------------
Write-Step "Python $minPython or newer"
$python = Find-Python
if ($python) {
    Write-Ok "Python $($python.Version) ($($python.Command -join ' '))"
} else {
    Write-Bad "Python $minPython+ was not found."
    if (Confirm-Action "Install Python 3.13 with winget?") {
        if (Install-WithWinget "Python.Python.3.13" "Python") { $python = Find-Python }
    }
    if ($python) { Write-Ok "Python $($python.Version) installed" }
    else { $missingRequired += "Python $minPython+ (https://www.python.org/downloads/windows/)" }
}

# --- 3. Virtual environment and Python packages ------------------------------
Write-Step "Lapicero packages (.venv)"
$venvReady = $false
if (Test-Path $venvPython) {
    & $venvPython -c "import PySide6, mcp" 2>$null
    $venvReady = ($LASTEXITCODE -eq 0)
}
if ($venvReady) {
    Write-Ok ".venv exists and has PySide6 and mcp"
    if (-not $CheckOnly -and -not $Yes -and (Confirm-Action "Re-install requirements.txt to make sure versions match?")) {
        & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root "requirements.txt")
    }
} elseif ($python) {
    Write-Warn ".venv is missing or incomplete."
    if (Confirm-Action "Create .venv and install requirements.txt?") {
        if (-not (Test-Path $venvPython)) {
            $exe = $python.Command[0]
            $rest = @($python.Command | Select-Object -Skip 1)
            & $exe @rest -m venv (Join-Path $root ".venv")
        }
        & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root "requirements.txt")
        if ($LASTEXITCODE -eq 0) { $venvReady = $true; Write-Ok "Packages installed" }
        else { Write-Bad "pip install failed (see the output above)." }
    }
    if (-not $venvReady) { $missingRequired += "Python packages (.venv)" }
} else {
    Write-Bad "Needs Python first."
    $missingRequired += "Python packages (.venv)"
}

# --- 4. Claude Code ----------------------------------------------------------
# Official docs: https://code.claude.com/docs/en/setup
Write-Step "Claude Code (for Ask Claude and the MCP tools)"
$claudeVersion = Get-ClaudeVersion
if ($claudeVersion) {
    Write-Ok "Claude Code $claudeVersion"
} else {
    Write-Warn "Claude Code was not found. Lapicero works without it, but Ask Claude needs it."
    if (Confirm-Action "Install Claude Code with the official native installer (irm https://claude.ai/install.ps1 | iex)?") {
        try {
            Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        } catch {
            Write-Bad "Native installer failed: $($_.Exception.Message)"
            if (Confirm-Action "Try winget instead (winget install Anthropic.ClaudeCode)?") {
                Install-WithWinget "Anthropic.ClaudeCode" "Claude Code" | Out-Null
            }
        }
        Update-SessionPath
        $claudeVersion = Get-ClaudeVersion
        if ($claudeVersion) { Write-Ok "Claude Code $claudeVersion installed" }
        else {
            Write-Warn "claude is still not on PATH. Open a new terminal and run: claude --version"
            Write-Warn "If it is not found, see https://code.claude.com/docs/en/troubleshoot-install"
        }
    }
}
if ($claudeVersion) {
    Write-Host "  Sign in once by running 'claude' in a terminal (needs a Pro, Max, Team, Enterprise or Console account)."
}

# --- 5. Git for Windows (optional) -------------------------------------------
Write-Step "Git for Windows (optional: gives Claude Code its Bash tool)"
if (Test-Command "git") {
    Write-Ok ((& git --version) | Select-Object -First 1)
} else {
    Write-Warn "Git for Windows is not installed. Claude Code falls back to PowerShell without it."
    if (Confirm-Action "Install Git for Windows with winget?") {
        if (Install-WithWinget "Git.Git" "Git for Windows") { Write-Ok "Git for Windows installed" }
    }
}

# --- 6. Shortcuts (optional) -------------------------------------------------
Write-Step "Shortcuts"
$desktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "Lapicero.lnk"
if (Test-Path $desktopLink) {
    Write-Ok "Desktop shortcut exists"
} elseif ($venvReady -and (Confirm-Action "Create Desktop and Start menu shortcuts (Ctrl+Alt+L)?")) {
    & (Join-Path $root "create_shortcut.ps1")
} else {
    Write-Warn "No Desktop shortcut."
}

# --- 7. MCP server in Claude Code (optional) ---------------------------------
Write-Step "Lapicero MCP server in Claude Code (optional)"
if ($claudeVersion -and $venvReady) {
    & claude mcp get lapicero *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "lapicero is already registered (claude mcp get lapicero)"
    } else {
        Write-Warn "lapicero is not registered, so Claude Code sessions cannot see your pages (Ask Claude still works)."
        if (Confirm-Action "Register the lapicero MCP server for your user in Claude Code?") {
            & claude mcp add lapicero --scope user -e "PYTHONPATH=$root" -- $venvPython -m lapicero.mcp_server
            if ($LASTEXITCODE -eq 0) { Write-Ok "Registered" } else { Write-Bad "claude mcp add failed (see the output above)." }
        }
    }
} else {
    Write-Warn "Skipped: needs Claude Code and the .venv."
}

# --- Summary -----------------------------------------------------------------
Write-Step "Summary"
if ($missingRequired.Count -eq 0) {
    Write-Ok "Lapicero is ready. Start it from the shortcut or with: .\.venv\Scripts\python main.py"
    exit 0
}
foreach ($item in $missingRequired) { Write-Bad "Missing: $item" }
exit 1
