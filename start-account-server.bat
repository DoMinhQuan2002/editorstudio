@echo off
chcp 65001 >NUL
title Media Studio - Account server (giu cua so nay mo)
cd /d "%~dp0server\account_api"
echo Admin page: http://127.0.0.1:8800/admin
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8800
pause
