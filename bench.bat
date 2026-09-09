@echo off
setlocal
title Shimmer - Listening bench
color 0B

REM ─────────────────────────────────────────────────────────────────────
REM bench.bat — open the listening bench.
REM
REM Same arrangement as references.bat: the bench is a page served by
REM Shimmer, not a separate program, so this is a shortcut rather than a
REM second launcher. It does NOT copy start.bat's setup (uv, the venv,
REM port handling, the readiness poll) — duplicating that is duplicating
REM the drift.
REM
REM If Shimmer is already up, this only opens the tab.
REM ─────────────────────────────────────────────────────────────────────

cd /d "%~dp0"

if not defined SHIMMER_PORT set "SHIMMER_PORT=7860"
set "PORT=%SHIMMER_PORT%"
set "PAGE=/static/ab/"
set "URL=http://localhost:%PORT%%PAGE%"

echo.
echo   Listening bench
echo   ---------------
echo   Two versions of the same music, both playing at once. One button
echo   swaps which one you hear - same instant, no gap. Levels are matched
echo   before anything is written, so you hear the difference and not the
echo   volume.
echo.
echo   Build something to listen to first:
echo     .venv\Scripts\python.exe scripts\make_bench_set.py both
echo.

REM Is Shimmer already answering? A raw TCP connect, for the same reason
REM open-when-ready.ps1 uses one: a web request carries proxy detection and
REM client startup that can time out while the server answers fine.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %PORT%); exit 0 } catch { exit 1 } finally { $c.Close() }" >nul 2>nul

if %errorlevel% equ 0 (
    echo   Shimmer is already running. Opening the page...
    echo   %URL%
    echo.
    start "" "%URL%"
    echo   If the page says the bench is empty, Shimmer was started before
    echo   the bench existed. Close it and run start.bat again.
    REM ping, not timeout: timeout fails outright when stdin is redirected,
    REM which happens whenever this is called from another script.
    ping -n 4 127.0.0.1 >nul 2>nul
    exit /b 0
)

echo   Shimmer is not running yet - starting it.
echo   %URL%
echo.
echo   Leave the window that opens. Closing it stops Shimmer.
echo.

set "SHIMMER_OPEN_PATH=%PAGE%"
call "%~dp0start.bat"
