@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\deploy_local.py" %*
) else (
    python "scripts\deploy_local.py" %*
)

echo.
pause
