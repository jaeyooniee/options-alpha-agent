param(
    [ValidateSet("SPY", "QQQ")]
    [string]$Underlying = "SPY",

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^\d{4}-\d{2}-\d{2}$")]
    [string]$Expiration,

    [ValidateRange(30, 300)]
    [int]$MaxAgeSeconds = 300,

    [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python executable not found at the requested workspace-relative path."
}

$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHHmmssZ")
$symbol = $Underlying.ToLowerInvariant()
$output = "data/options/$symbol.indicative.$timestamp.csv"

& $Python -m options_alpha_agent.cli capture-option-snapshot `
    --underlying $Underlying `
    --expiration $Expiration `
    --output $output `
    --max-age-seconds $MaxAgeSeconds
if ($LASTEXITCODE -ne 0) {
    throw "Read-only option snapshot capture failed."
}

& $Python -m options_alpha_agent.cli option-snapshot-check --csv $output
if ($LASTEXITCODE -ne 0) {
    throw "The captured snapshot did not pass strict validation."
}

Write-Output "Validated immutable snapshot: $output"
Write-Output "order_sent=false"
