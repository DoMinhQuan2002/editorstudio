# Installs the optional AI libraries for Fashion Studio into the backend venv.
# Run from the backend folder:  powershell -ExecutionPolicy Bypass -File .\setup-fashion.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Không thấy backend\.venv. Chạy setup.ps1 trước." }

Write-Host "1/3 Cài PyTorch bản CUDA 12.8..."
& $python -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu128

Write-Host "2/3 Cài diffusers, transformers, accelerate, bitsandbytes..."
& $python -m pip install --upgrade -r requirements-fashion.txt

Write-Host "3/3 Kiểm tra..."
& $python -c "import torch, diffusers; from diffusers import QwenImageEditPlusPipeline; print('torch', torch.__version__, 'CUDA', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''); print('diffusers', diffusers.__version__)"
if ($LASTEXITCODE -ne 0) {
  Write-Host "diffusers bản phát hành chưa có QwenImageEditPlusPipeline, cài bản mới nhất từ GitHub..."
  & $python -m pip install --upgrade git+https://github.com/huggingface/diffusers
}
Write-Host "Xong. Khởi động lại Media Studio, vào Fashion Studio và bấm 'Tải model'."
