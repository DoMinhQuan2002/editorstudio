param(
    [switch]$EnableGuidedBackgroundExclusion
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repoRoot "src\MediaStudio.Desktop\MediaStudio.Desktop.csproj"
$previousFlag = [Environment]::GetEnvironmentVariable("MEDIASTUDIO_FOREGROUND_PROTECTION_LAB", "Process")
$previousBackgroundExclusionFlag = [Environment]::GetEnvironmentVariable("MEDIASTUDIO_GUIDED_BACKGROUND_EXCLUSION", "Process")

try {
    $env:MEDIASTUDIO_FOREGROUND_PROTECTION_LAB = "1"
    $env:MEDIASTUDIO_GUIDED_BACKGROUND_EXCLUSION = if ($EnableGuidedBackgroundExclusion) { "1" } else { "0" }
    dotnet run --project $project
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    if ($null -eq $previousFlag) {
        Remove-Item Env:MEDIASTUDIO_FOREGROUND_PROTECTION_LAB -ErrorAction SilentlyContinue
    }
    else {
        $env:MEDIASTUDIO_FOREGROUND_PROTECTION_LAB = $previousFlag
    }
    if ($null -eq $previousBackgroundExclusionFlag) {
        Remove-Item Env:MEDIASTUDIO_GUIDED_BACKGROUND_EXCLUSION -ErrorAction SilentlyContinue
    }
    else {
        $env:MEDIASTUDIO_GUIDED_BACKGROUND_EXCLUSION = $previousBackgroundExclusionFlag
    }
}
