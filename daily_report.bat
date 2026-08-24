@echo off
title Daily Report and Push
cd /d "%~dp0"

rem Prefer project venv Python, fallback to system Python
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/5] Portfolio fund report...
"%PY%" Code\portfolio_report.py
if errorlevel 1 goto :err

echo.
echo [2/5] Sector plate report...
"%PY%" Code\plate_report.py
if errorlevel 1 goto :err

echo.
echo [3/5] ETF entry report...
"%PY%" Code\etf_report.py
if errorlevel 1 goto :err

echo.
echo [4/5] Refresh index.html...
"%PY%" Code\make_index.py
if errorlevel 1 goto :err

echo.
echo [5/5] Git commit and push...
git add .
git diff --cached --quiet
if errorlevel 1 (
    git commit -F Code\_commit_msg.txt
    if errorlevel 1 goto :err
    git push
    if errorlevel 1 goto :err
    echo Committed and pushed.
) else (
    echo Nothing to commit.
)

echo.
echo All done!
pause
exit /b 0

:err
echo.
echo [FAILED] Step error, commit skipped. Check log above.
pause
exit /b 1
