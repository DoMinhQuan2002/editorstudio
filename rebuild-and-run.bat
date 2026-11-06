@echo off
cd /d "%~dp0"
echo Dang tat Media Studio cu...
taskkill /IM MediaStudio.Desktop.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
echo Dang build...
dotnet build src\MediaStudio.Desktop\MediaStudio.Desktop.csproj > build-log.txt 2>&1
if errorlevel 1 (
  echo BUILD LOI - xem build-log.txt
  type build-log.txt
  pause
  exit /b 1
)
echo Build xong, dang mo app...
start "" "src\MediaStudio.Desktop\bin\Debug\net10.0-windows\MediaStudio.Desktop.exe"
