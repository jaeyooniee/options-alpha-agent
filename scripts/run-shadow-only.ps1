param(
    [int]$Cycles = 1,
    [int]$IntervalSeconds = 60,
    [string]$Underlying = "SPY"
)

if ($Cycles -lt 1) {
    throw "Cycles must be at least 1. Re-run with an explicit finite cycle count."
}
if ($IntervalSeconds -lt 10 -or $IntervalSeconds -gt 3600) {
    throw "IntervalSeconds must be between 10 and 3600."
}

# These process-local values override any accidental execution setting in .env.
# This script is intentionally incapable of submitting a paper order.
$env:TRADE_EXECUTION_ENABLED = "false"
$env:PAPER_ORDER_APPROVED = "false"
$env:TRADING_KILL_SWITCH = "true"
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"

for ($index = 1; $index -le $Cycles; $index++) {
    Write-Host ("shadow-only cycle {0}/{1}" -f $index, $Cycles)
    & $python -m options_alpha_agent shadow-cycle --underlying $Underlying
    if ($LASTEXITCODE -ne 0) {
        throw "shadow-cycle failed with exit code $LASTEXITCODE"
    }
    if ($index -lt $Cycles) {
        Start-Sleep -Seconds $IntervalSeconds
    }
}
