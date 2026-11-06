$ErrorActionPreference = "Stop"

$visualStudioRoot = "C:\Program Files\Microsoft Visual Studio\18\CommunityMediaStudioCpp"
$cmake = Join-Path $visualStudioRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$vcpkgRoot = Join-Path $visualStudioRoot "VC\vcpkg"
$toolchain = Join-Path $vcpkgRoot "scripts\buildsystems\vcpkg.cmake"
$buildDirectory = Join-Path $env:LOCALAPPDATA "MediaStudio\VideoEngineBuild"
$runtimeDirectory = Join-Path $PSScriptRoot "build-msvc-x64\Release"

foreach ($requiredPath in @($cmake, $toolchain)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Không tìm thấy công cụ cần thiết: $requiredPath"
    }
}

$env:VCPKG_ROOT = $vcpkgRoot
& $cmake -S $PSScriptRoot -B $buildDirectory `
    -G "Visual Studio 18 2026" -A x64 `
    "-DCMAKE_GENERATOR_INSTANCE=$visualStudioRoot" `
    "-DCMAKE_TOOLCHAIN_FILE=$toolchain"
if ($LASTEXITCODE -ne 0) {
    throw "CMake configure thất bại với mã $LASTEXITCODE."
}

& $cmake --build $buildDirectory --config Release
if ($LASTEXITCODE -ne 0) {
    throw "Biên dịch native video engine thất bại với mã $LASTEXITCODE."
}

New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
Get-ChildItem -Path (Join-Path $buildDirectory "Release") -Filter "*.dll" -File |
    Copy-Item -Destination $runtimeDirectory -Force

Write-Host "Native video engine đã được build tại: $runtimeDirectory"
