[CmdletBinding()]
param(
    [string]$Python = ".venv\Scripts\python.exe",
    [switch]$RequireStaged
)

# Read-only release gate. This script never commits, pushes, creates a repository,
# deploys, uploads, or sends an order.
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-Checked {
    param([string[]]$Command)

    & $Command[0] $Command[1..($Command.Count - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $($Command -join ' ')"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required for release preflight."
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python executable not found at the requested workspace-relative path."
}

# This one-command exception is read-only and avoids changing the user's global
# Git configuration. `docs/local-git-setup.md` explains the persistent fix.
$gitPrefix = @("git", "-c", "safe.directory=$projectRoot")
$name = "$(& $gitPrefix[0] $gitPrefix[1..2] config --get user.name)"
$email = "$(& $gitPrefix[0] $gitPrefix[1..2] config --get user.email)"
$name = $name.Trim()
$email = $email.Trim()
if (-not $name) {
    throw "Repository-local git user.name is missing. See docs/local-git-setup.md."
}
if ($email -notmatch "^[^@\s]+@users\.noreply\.github\.com$") {
    throw "Repository-local git user.email must use a GitHub users.noreply.github.com address."
}

$savedErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$trackedEnv = & $gitPrefix[0] $gitPrefix[1..2] ls-files --error-unmatch .env 2>$null
$trackedEnvExit = $LASTEXITCODE
$ErrorActionPreference = $savedErrorAction
if ($trackedEnvExit -eq 0 -or $trackedEnv) {
    throw ".env is tracked; remove it from the Git index before any commit."
}
if ($trackedEnvExit -gt 1) {
    throw "Unable to inspect whether .env is tracked."
}

Invoke-Checked @($Python, "-m", "ruff", "format", "--check", ".")
Invoke-Checked @($Python, "-m", "ruff", "check", ".")
Invoke-Checked @($Python, "-m", "pytest", "-q")
Invoke-Checked @($Python, "-m", "options_alpha_agent.cli", "submission-check")

$stagedFiles = @(& $gitPrefix[0] $gitPrefix[1..2] diff --cached --name-only)
if ($RequireStaged -and -not $stagedFiles) {
    throw "No staged files. Run git add -A, inspect the staged names, then retry."
}
if ($stagedFiles) {
    Invoke-Checked @($gitPrefix + @("diff", "--cached", "--check"))
    $savedErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $secretMatches = & $gitPrefix[0] $gitPrefix[1..2] grep --cached -n -I -E `
        -e "ALPACA_API_KEY=[^[:space:]]+" `
        -e "ALPACA_SECRET_KEY=[^[:space:]]+" `
        -e "FEATHERLESS_API_KEY=[^[:space:]]+" `
        -e "OPENAI_API_KEY=[^[:space:]]+" `
        -- ':!docs/local-git-setup.md' ':!scripts/release-preflight.ps1' ':!tests/test_submission_check.py'
    $secretScanExit = $LASTEXITCODE
    $ErrorActionPreference = $savedErrorAction
    if ($secretScanExit -eq 0 -or $secretMatches) {
        throw "Secret-like environment assignment found in the staged content."
    }
    if ($secretScanExit -gt 1) {
        throw "Unable to scan staged content for secret-like assignments."
    }
}

Write-Output "release_preflight=ready"
Write-Output "git_identity=$name <$email>"
Write-Output "staged_file_count=$($stagedFiles.Count)"
Write-Output "public_push=false"
Write-Output "deployment=false"
Write-Output "order_sent=false"
