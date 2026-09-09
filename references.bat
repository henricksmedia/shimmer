@echo off
setlocal
title Shimmer - Reference library
color 0B

REM ─────────────────────────────────────────────────────────────────────
REM references.bat — open the reference library.
REM
REM The library is a page served by Shimmer, not a separate program, so
REM this is a shortcut rather than a second launcher. It does NOT copy
REM start.bat's setup (uv, the venv, port handling, the readiness poll) —
REM two hundred lines duplicated is two hundred lines to drift.
REM
REM If Shimmer is already up, this only opens the tab. Handing off to
REM start.bat in that case would kill the running server and restart it,
REM which is a rude thing for a shortcut to do while you are working.
REM ─────────────────────────────────────────────────────────────────────

cd /d "%~dp0"

if not defined SHIMMER_PORT set "SHIMMER_PORT=7860"
set "PORT=%SHIMMER_PORT%"
set "PAGE=/static/references/"
set "URL=http://localhost:%PORT%%PAGE%"

echo.
echo   Reference library
echo   -----------------
echo   Play music, and Shimmer measures its tone. The audio is thrown
echo   away; only the curve is kept. That curve is what the tone target
echo   is built from.
echo.

REM Is Shimmer already answering on this port? A raw TCP connect, for the
REM same reason open-when-ready.ps1 uses one: a web request carries proxy
REM detection and client startup that can time out while the server is
REM answering perfectly well.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %PORT%); exit 0 } catch { exit 1 } finally { $c.Close() }" >nul 2>nul

if %errorlevel% equ 0 (
    echo   Shimmer is already running. Opening the page...
    echo   %URL%
    echo.
    start "" "%URL%"
    echo   Leave the Shimmer window open while you capture.
    REM ping, not timeout: timeout fails outright when stdin is redirected
    REM ("Input redirection is not supported"), which happens whenever this
    REM is called from another script rather than double-clicked.
    ping -n 4 127.0.0.1 >/dev/null 2>&1
    exit /b 0
)

echo   Shimmer is not running yet - starting it.
echo   %URL%
echo.
echo   Leave the window that opens. Closing it stops Shimmer.
echo.

REM start.bat does the real work and opens this page instead of the app.
set "SHIMMER_OPEN_PATH=%PAGE%"
call "%~dp0start.bat"
