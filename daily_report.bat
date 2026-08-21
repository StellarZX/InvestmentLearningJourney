@echo off
title Daily Report and Push
cd /d "%~dp0"

rem Prefer project venv Python, fallback to system Python
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/4] Portfolio fund report...
"%PY%" Code\portfolio_report.py
if errorlevel 1 goto :err

echo.
echo [2/4] Sector plate report...
"%PY%" Code\plate_report.py
if errorlevel 1 goto :err

echo.
echo [3/4] Refresh index.html...
"%PY%" Code\make_index.py
if errorlevel 1 goto :err

echo.
echo [4/4] Git commit and push...
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
