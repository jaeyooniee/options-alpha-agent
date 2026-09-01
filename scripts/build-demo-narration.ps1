param(
    [string]$SsmlPath = "scripts\demo-narration.ssml",
    [string]$Output = "artifacts\demo-narration.wav",
    [string]$Voice = "Microsoft Zira Desktop",
    [ValidateRange(-10, 10)]
    [int]$Rate = 0,
    [switch]$Overwrite
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path -LiteralPath ".").Path
$inputPath = (Resolve-Path -LiteralPath $SsmlPath).Path
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $workspace $Output))

if (-not $outputPath.StartsWith($workspace + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "Output must remain inside the workspace."
}
if ((Test-Path -LiteralPath $outputPath) -and -not $Overwrite) {
    throw "Output already exists; pass -Overwrite for an intentional replacement."
}

$outputDirectory = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

$voiceObject = New-Object -ComObject SAPI.SpVoice
$stream = New-Object -ComObject SAPI.SpFileStream
$format = New-Object -ComObject SAPI.SpAudioFormat
try {
    $selectedVoice = $null
    $availableDescriptions = @()
    $voices = $voiceObject.GetVoices()
    for ($index = 0; $index -lt $voices.Count; $index += 1) {
        $candidate = $voices.Item($index)
        $description = $candidate.GetDescription()
        $availableDescriptions += $description
        if ($description -eq $Voice -or $description.StartsWith($Voice + " - ")) {
            $selectedVoice = $candidate
            $selectedDescription = $description
            break
        }
    }
    if ($null -eq $selectedVoice) {
        throw "Requested Windows SAPI voice is not installed. Available: $($availableDescriptions -join ', ')"
    }

    $voiceObject.Voice = $selectedVoice
    $voiceObject.Rate = $Rate
    $voiceObject.Volume = 100
    $format.Type = 22
    $stream.Format = $format
    $stream.Open($outputPath, 3, $false)
    $voiceObject.AudioOutputStream = $stream
    [void]$voiceObject.Speak((Get-Content -LiteralPath $inputPath -Raw -Encoding UTF8), 8)
    $stream.Close()
}
finally {
    foreach ($comObject in @($selectedVoice, $format, $stream, $voiceObject)) {
        if ($null -ne $comObject -and [System.Runtime.InteropServices.Marshal]::IsComObject($comObject)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($comObject)
        }
    }
}

$item = Get-Item -LiteralPath $outputPath
[pscustomobject]@{
    status = "ok"
    output = $item.FullName
    voice = $selectedDescription
    rate = $Rate
    bytes = $item.Length
} | ConvertTo-Json
