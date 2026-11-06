$ErrorActionPreference = 'Stop'
$backendDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$environmentDirectory = Join-Path $backendDirectory '.venv'
$python = Join-Path $environmentDirectory 'Scripts\python.exe'
$toolsDirectory = Join-Path $backendDirectory 'tools'
$potraceDirectory = Join-Path $toolsDirectory 'potrace-1.16.win64'
$potraceExecutable = Join-Path $potraceDirectory 'potrace.exe'

if (-not (Test-Path -LiteralPath $python)) {
    py -3.12 -m venv $environmentDirectory
}

if (-not (Test-Path -LiteralPath $potraceExecutable)) {
    New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null
    $archive = Join-Path $env:TEMP 'mediastudio-potrace-1.16.win64.zip'
    Invoke-WebRequest -Uri 'https://potrace.sourceforge.net/download/1.16/potrace-1.16.win64.zip' -OutFile $archive
    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA1).Hash
    if ($actualHash -ne '7E360015C8AC0E6EFDFFA6C26974DAF65AB596E9') {
        Remove-Item -LiteralPath $archive -Force
        throw 'Bản tải Potrace không khớp SHA-1 chính thức.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $toolsDirectory -Force
    Remove-Item -LiteralPath $archive -Force
}

& $python -m pip install --upgrade pip
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    & $python -m pip install 'torch==2.6.0' 'torchvision==0.21.0' --index-url https://download.pytorch.org/whl/cu126
} else {
    & $python -m pip install 'torch==2.6.0' 'torchvision==0.21.0' --index-url https://download.pytorch.org/whl/cpu
}
& $python -m pip install -r (Join-Path $backendDirectory 'requirements.txt')
& $python -m pip install --no-deps -r (Join-Path $backendDirectory 'requirements-ocr.txt')
& $python -c "import torch; print(f'PyTorch {torch.__version__}; CUDA available: {torch.cuda.is_available()}')"
