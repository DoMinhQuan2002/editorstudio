@echo off
chcp 65001 >NUL
cd /d "%~dp0"
title Tai model Qwen-Image-Edit-2511
set PY=%~dp0backend\.venv\Scripts\python.exe
echo ============================================================
echo  Tai ma nguon Qwen-Image (GitHub) va model Qwen-Image-Edit-2511
echo  Model khoang 55-60 GB. Co the tat roi chay lai: se tai tiep.
echo ============================================================
if not exist "third_party\Qwen-Image" (
  git clone --depth 1 https://github.com/QwenLM/Qwen-Image "third_party\Qwen-Image"
)
set HF_HUB_ENABLE_HF_TRANSFER=0
"%PY%" -c "from huggingface_hub import snapshot_download; p=snapshot_download('Qwen/Qwen-Image-Edit-2511', local_dir=r'%~dp0models\Qwen-Image-Edit-2511', max_workers=8); print('DA TAI XONG:', p)"
if errorlevel 1 (
  echo.
  echo TAI THAT BAI. Chay lai file nay de tai tiep phan con thieu.
) else (
  echo.
  echo XONG. Mo Media Studio ^> Fashion Studio ^> Kiem tra lai.
)
pause
