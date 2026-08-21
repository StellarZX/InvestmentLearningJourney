@echo off
title Portfolio Manager
cd /d "%~dp0"

rem Prefer project venv Python, fallback to system Python
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================
echo   Portfolio manager starting...
echo   Browser will open http://127.0.0.1:8051
echo   Close this window to stop the server.
echo ================================================
"%PY%" Code\portfolio_app.py
pause
