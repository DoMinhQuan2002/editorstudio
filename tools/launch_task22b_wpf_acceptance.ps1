[CmdletBinding()]
param(
    [string]$BuildDirectory = "artifacts\video_editor\task2_2b_validation\desktop-build",
    [string]$DataDirectory = "artifacts\video_editor\task2_2b_validation\runtime-data",
    [string]$ArtifactDirectory = "artifacts\video_editor\task2_2b_validation"
)

$ErrorActionPreference = "Stop"
$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $BuildDirectory))
$dataRoot = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $DataDirectory))
$artifactRoot = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $ArtifactDirectory))
$appPath = Join-Path $buildRoot "MediaStudio.Desktop.exe"
$pythonPath = Join-Path $workspaceRoot "backend\.venv\Scripts\python.exe"
$fixtureScript = Join-Path $workspaceRoot "backend\tools\prepare_task22b_wpf_fixture.py"
$logPath = Join-Path $artifactRoot ("backend-wpf-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

if (-not (Test-Path -LiteralPath $appPath -PathType Leaf)) {
    throw "Validation build not found: $appPath"
}
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Backend Python environment not found: $pythonPath"
}
if (-not (Test-Path -LiteralPath $fixtureScript -PathType Leaf)) {
    throw "Fixture generator not found: $fixtureScript"
}

New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
$fixtureMarker = Join-Path $dataRoot "task22b_fixture_manifest.json"
if (-not (Test-Path -LiteralPath $fixtureMarker -PathType Leaf)) {
    $env:PYTHONPATH = Join-Path $workspaceRoot "backend"
    & $pythonPath $fixtureScript --data-directory $dataRoot --artifact-directory $artifactRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not prepare the isolated TASK 2.2B project fixture."
    }
}

$enginePath = Join-Path $buildRoot "mediastudio_video_engine.dll"
$savedDataDirectory = $env:MEDIASTUDIO_DATA_DIRECTORY
$savedLogPath = $env:MEDIASTUDIO_BACKEND_LOG_PATH
$savedEnginePath = $env:MEDIASTUDIO_VIDEO_ENGINE_PATH
$savedPythonPath = $env:PYTHONPATH
$savedWorkingDirectory = Get-Location
try {
    $env:MEDIASTUDIO_DATA_DIRECTORY = $dataRoot
    $env:MEDIASTUDIO_BACKEND_LOG_PATH = $logPath
    if (Test-Path -LiteralPath $enginePath -PathType Leaf) {
        $env:MEDIASTUDIO_VIDEO_ENGINE_PATH = $enginePath
    }
    Set-Location -LiteralPath $workspaceRoot
    Write-Host "Opening isolated TASK 2.2B validation build: $appPath"
    Write-Host "Project data: $dataRoot"
    Write-Host "Backend log: $logPath"
    $appProcess = Start-Process -FilePath $appPath -WorkingDirectory $workspaceRoot `
        -WindowStyle Normal -PassThru
    Write-Host "Media Studio is running (PID $($appProcess.Id)). Close the app to finish this test session."
}
finally {
    Set-Location -LiteralPath $savedWorkingDirectory
    if ($null -eq $savedDataDirectory) { Remove-Item Env:MEDIASTUDIO_DATA_DIRECTORY -ErrorAction SilentlyContinue }
    else { $env:MEDIASTUDIO_DATA_DIRECTORY = $savedDataDirectory }
    if ($null -eq $savedLogPath) { Remove-Item Env:MEDIASTUDIO_BACKEND_LOG_PATH -ErrorAction SilentlyContinue }
    else { $env:MEDIASTUDIO_BACKEND_LOG_PATH = $savedLogPath }
    if ($null -eq $savedEnginePath) { Remove-Item Env:MEDIASTUDIO_VIDEO_ENGINE_PATH -ErrorAction SilentlyContinue }
    else { $env:MEDIASTUDIO_VIDEO_ENGINE_PATH = $savedEnginePath }
    if ($null -eq $savedPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $savedPythonPath }
}
