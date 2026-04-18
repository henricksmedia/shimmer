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

if not exist ".deps_installed" (
    echo  Installing dependencies...
    pip install -r requirements.txt -q
    if %errorlevel% neq 0 (
        echo  Failed to install dependencies
        pause
        exit /b 1
    )
    echo.> .deps_installed
    echo  Dependencies installed
    echo.
)

REM Kill any leftover process on port 7860
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :7860 ^| findstr LISTENING 2^>nul') do (
    echo  Closing previous session...
    taskkill /PID %%a /F >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo  Starting Shimmer server...
echo  http://localhost:7860
echo.

REM Open the browser after a short delay so the server has time to bind.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:7860"

python -m uvicorn server:app --host 127.0.0.1 --port 7860 --log-level warning
if %errorlevel% neq 0 (
    echo.
    echo  Port may still be releasing. Retrying in 3 seconds...
    timeout /t 3 /nobreak >nul
    python -m uvicorn server:app --host 127.0.0.1 --port 7860 --log-level warning
)

pause
