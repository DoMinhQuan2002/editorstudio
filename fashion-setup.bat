@echo off
cd /d "%~dp0"
set LOG=%~dp0fashion-setup-log.txt
echo ==== Kiem tra may ==== > "%LOG%"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv >> "%LOG%" 2>&1
powershell -NoProfile -Command "'RAM_GB=' + [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB); 'C_FREE_GB=' + [math]::Round((Get-PSDrive C).Free/1GB)" >> "%LOG%" 2>&1
echo ==== Cai thu vien Fashion Studio ==== >> "%LOG%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backend\setup-fashion.ps1" >> "%LOG%" 2>&1
echo ==== XONG (exit %ERRORLEVEL%) ==== >> "%LOG%"
