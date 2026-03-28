@echo off
title Stock AI API

echo =========================================
echo   Stock AI Trading API v3
echo =========================================
echo.

cd /d %~dp0

echo   Starting server...
echo   Dashboard: http://localhost:8000/dashboard
echo   API Docs: http://localhost:8000/docs
echo   Stop: Close this window or Ctrl+C
echo =========================================
echo.

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
