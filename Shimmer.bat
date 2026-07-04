@echo off
title Shimmer by The Treq
color 05

echo.
echo  ========================================
echo       SHIMMER by The Treq
echo       AI Audio De-Artifact Tool
echo  ========================================
echo.

cd /d "%~dp0"

REM uv manages an isolated, hardlinked .venv for this project so installs
REM never touch the global Python and disk usage stays minimal.
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo  uv was not found on PATH.
    echo  Install with:  winget install --id=astral-sh.uv -e
    echo  Or see:        https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

REM Create the local venv on first run (no-op if already present)
if not exist ".venv\Scripts\python.exe" (
    echo  Creating local Python environment with uv...
    uv venv
    if %errorlevel% neq 0 (
        echo  Failed to create venv.
        pause
        exit /b 1
    )
)

set "PY=.venv\Scripts\python.exe"

REM Probe imports instead of trusting a sentinel file. A real import test
REM is the only way to know the venv actually has what we need.
"%PY%" -c "import fastapi, uvicorn, numpy, scipy, soundfile, pydub" 1>nul 2>nul
if %errorlevel% neq 0 (
    echo  Installing dependencies with uv...
    uv pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo  Failed to install dependencies.
        pause
        exit /b 1
    )
    echo  Dependencies installed
    echo.
)

REM Kill any leftover process on port 7860.
REM netstat is fast and pure-Win32 (no WMI dependency). We pass each PID to
REM PowerShell's Stop-Process, which calls TerminateProcess directly and
REM cannot hang the way `taskkill /F` does when WMI is unhealthy.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :7860 ^| findstr LISTENING 2^>nul') do (
    echo  Closing previous session...
    powershell -NoProfile -Command "Stop-Process -Id %%a -Force -ErrorAction SilentlyContinue"
)

echo  Starting Shimmer server...
echo  http://localhost:7860
echo.

REM Open the browser after a short delay so the server has time to bind.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:7860"

"%PY%" -m uvicorn server:app --host 127.0.0.1 --port 7860 --log-level warning
if %errorlevel% neq 0 (
    echo.
    echo  Port may still be releasing. Retrying in 3 seconds...
    timeout /t 3 /nobreak >nul
    "%PY%" -m uvicorn server:app --host 127.0.0.1 --port 7860 --log-level warning
)

pause
