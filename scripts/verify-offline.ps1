$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$ruffPath = Join-Path $projectRoot ".venv\Scripts\ruff.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Missing .venv\Scripts\python.exe. Create the virtual environment first."
}
if (-not (Test-Path -LiteralPath $ruffPath)) {
    throw "Missing .venv\Scripts\ruff.exe. Install the dev dependencies first."
}

$env:PYTHONPATH = "src"
$pytestBaseTemp = Join-Path $projectRoot "pytest-tmp-$([guid]::NewGuid().ToString('N'))"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Write-Host "== $Label =="
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Invoke-CheckedCommand "ruff lint" $ruffPath @("check", ".")
Invoke-CheckedCommand "ruff format" $ruffPath @("format", "--check", ".")
Invoke-CheckedCommand "compileall" $pythonPath @("-m", "compileall", "-q", "src", "tests")
Invoke-CheckedCommand "pytest" $pythonPath @(
    "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", $pytestBaseTemp
)
Invoke-CheckedCommand "offline demo" $pythonPath @("-m", "options_alpha_agent", "demo")
Invoke-CheckedCommand "shadow performance" $pythonPath @(
    "-m", "options_alpha_agent", "shadow-performance", "--horizon-hours", "24"
)
Invoke-CheckedCommand "option snapshot" $pythonPath @(
    "-m", "options_alpha_agent", "option-snapshot-check", "--csv",
    "data/options/spy.indicative.2026-08-28T1948Z.csv"
)
Invoke-CheckedCommand "second option snapshot" $pythonPath @(
    "-m", "options_alpha_agent", "option-snapshot-check", "--csv",
    "data/options/spy.indicative.2026-08-28T1957Z.csv"
)
Invoke-CheckedCommand "option snapshot comparison" $pythonPath @(
    "-m", "options_alpha_agent", "option-snapshot-compare", "--entry",
    "data/options/spy.indicative.2026-08-28T1948Z.csv", "--exit",
    "data/options/spy.indicative.2026-08-28T1957Z.csv"
)
Invoke-CheckedCommand "replay" $pythonPath @(
    "-m", "options_alpha_agent", "replay", "--csv", "data/replay.sample.csv"
)
Invoke-CheckedCommand "walk-forward" $pythonPath @(
    "-m", "options_alpha_agent", "walk-forward", "--csv", "data/underlying.sample.csv",
    "--holdout-bars", "10"
)
Invoke-CheckedCommand "robustness" $pythonPath @(
    "-m", "options_alpha_agent", "robustness", "--paths", "1000"
)

Write-Host "Offline preflight passed. No broker order or provider inference was requested."
