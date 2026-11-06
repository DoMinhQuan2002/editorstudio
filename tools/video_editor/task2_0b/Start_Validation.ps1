param(
    [string]$ValidationRoot = 'D:\MediaStudioTask2Validation_20261021_1328',
    [string]$Workspace = 'C:\Users\Quan\Documents\ChatGPT\Unkown app',
    [string]$AppExecutable = 'C:\Users\Quan\Documents\ChatGPT\Unkown app\artifacts\validation-task2-0a-wpf\MediaStudio.Desktop.exe',
    [string]$ExpectedNativeDllSha256 = 'B9CEA237317227B73ECAECCE7F0252689AEC2C11B8CBCB360752D089C584D3DF'
)

$ErrorActionPreference = 'Stop'
$sessionRoot = Join-Path $ValidationRoot 'wpf-live-2_0b'
$dataDirectory = Join-Path $sessionRoot 'data'
$modelsDirectory = Join-Path $sessionRoot 'models'
$backendLog = Join-Path $sessionRoot 'backend.log'
$sessionState = Join-Path $sessionRoot 'session-state.json'
$dragLog = Join-Path $env:LOCALAPPDATA 'MediaStudio\VideoEditor\timeline-drag-diagnostics.jsonl'
$nativeDll = Join-Path (Split-Path -Parent $AppExecutable) 'mediastudio_video_engine.dll'

if (-not (Test-Path -LiteralPath $AppExecutable)) { throw "Không tìm thấy WPF validation app: $AppExecutable" }
if (-not (Test-Path -LiteralPath $nativeDll)) { throw "Không tìm thấy native DLL bên cạnh app: $nativeDll" }
if (Test-Path -LiteralPath $sessionState) {
    throw "Phiên Task 2.0B này đã được khởi chạy. Dùng cửa sổ hiện tại; để tạo phiên mới hãy chỉ định ValidationRoot mới."
}
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $nativeDll).Hash
if ($actualHash -ne $ExpectedNativeDllSha256) {
    throw "SHA-256 native DLL không khớp Task 2.0A. Expected=$ExpectedNativeDllSha256 Actual=$actualHash"
}
if (Test-Path -LiteralPath $dataDirectory) {
    if (@(Get-ChildItem -LiteralPath $dataDirectory -Recurse -File -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "Data directory đã có file; không dùng lại để tránh ghi đè hoặc mở trùng phiên. Hãy dùng app test hiện có hoặc ValidationRoot mới."
    }
} else {
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
}
New-Item -ItemType Directory -Path $modelsDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null

$dragOffset = 0
if (Test-Path -LiteralPath $dragLog) { $dragOffset = (Get-Item -LiteralPath $dragLog).Length }
$startedAt = [DateTimeOffset]::Now
$state = [pscustomobject]@{
    task = '2.0B'
    startedAt = $startedAt.ToString('o')
    appExecutable = $AppExecutable
    appSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $AppExecutable).Hash
    nativeDll = $nativeDll
    nativeDllSha256 = $actualHash
    dataDirectory = $dataDirectory
    modelsDirectory = $modelsDirectory
    backendLog = $backendLog
    dragLog = $dragLog
    dragLogByteOffset = $dragOffset
}
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $sessionState -Encoding UTF8

$env:MEDIASTUDIO_DATA_DIRECTORY = $dataDirectory
$env:MEDIASTUDIO_MODELS_DIRECTORY = $modelsDirectory
$env:MEDIASTUDIO_BACKEND_LOG_PATH = $backendLog
$env:MEDIASTUDIO_TIMELINE_DRAG_DIAGNOSTICS = '1'

$app = Start-Process -FilePath $AppExecutable -WorkingDirectory $Workspace -PassThru
Write-Output "WPF validation app PID: $($app.Id)"
Write-Output "Started at: $($startedAt.ToString('o'))"
Write-Output "Data directory: $dataDirectory"
Write-Output "Backend log: $backendLog"
Write-Output "Timeline drag log: $dragLog (read only from byte offset $dragOffset)"
Write-Output "Session state: $sessionState"
Write-Output "Native DLL SHA-256: $actualHash"
