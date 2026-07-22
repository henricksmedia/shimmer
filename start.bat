@echo off
setlocal
title Shimmer by The Treq
color 0D

REM Banner: figlet-style wordmark. Pipes/angle brackets are caret-escaped
REM (^| ^<) so cmd prints them literally — edit with care.
echo.
echo      *   .        .      *          .          *   .
echo      ____   _   _  ___  __  __  __  __  _____  ____
echo     / ___^| ^| ^| ^| ^|^|_ _^|^|  \/  ^|^|  \/  ^|^| ____^|^|  _ \
echo     \___ \ ^| ^|_^| ^| ^| ^| ^| ^|\/^| ^|^| ^|\/^| ^|^|  _^|  ^| ^|_) ^|
echo      ___) ^|^|  _  ^| ^| ^| ^| ^|  ^| ^|^| ^|  ^| ^|^| ^|___ ^|  _ ^<
echo     ^|____/ ^|_^| ^|_^|^|___^|^|_^|  ^|_^|^|_^|  ^|_^|^|_____^|^|_^| \_\
echo        .          *                        by The Treq
echo.
echo     -------------------------------------------------
echo       de-artifact . restore . master . shine
echo           treqmusic.com/tools/shimmer
echo     -------------------------------------------------
echo.

cd /d "%~dp0"

REM Port can be overridden:  set SHIMMER_PORT=7870 && start.bat
if not defined SHIMMER_PORT set "SHIMMER_PORT=7860"
set "PORT=%SHIMMER_PORT%"
set "URL=http://localhost:%PORT%"

REM ── Step 1: uv ────────────────────────────────────────────────────────
REM uv manages an isolated, hardlinked .venv for this project so installs
REM never touch the global Python and disk usage stays minimal. It also
REM downloads the right Python version by itself, so it is the only
REM prerequisite.
where uv >nul 2>nul
if %errorlevel% equ 0 goto :uv_ready

echo  FIRST-TIME SETUP
echo  ----------------
echo  Shimmer needs a free tool called "uv" to install itself.
echo  It handles Python and all the audio libraries for you.
echo.
set "DOUV="
set /p DOUV=Install uv now? [Y/n]:
if /i "%DOUV%"=="n" goto :uv_manual

where winget >nul 2>nul
if %errorlevel% neq 0 goto :uv_manual

echo.
echo  Installing uv (this takes about a minute)...
winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
echo.

REM winget updates PATH for NEW shells only, so re-check both PATH and the
REM standard per-user install location before giving up.
where uv >nul 2>nul
if %errorlevel% equ 0 goto :uv_ready
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    goto :uv_ready
)

echo  uv was installed but this window cannot see it yet.
echo  Close this window and double-click start.bat again.
echo.
pause
exit /b 0

:uv_manual
echo.
echo  To install uv manually, run this in a terminal:
echo      winget install --id=astral-sh.uv -e
echo  Or follow: https://docs.astral.sh/uv/getting-started/installation/
echo.
echo  Then double-click start.bat again.
pause
exit /b 1

:uv_ready

REM ── Step 2: local environment ─────────────────────────────────────────
REM NOTE: no nested parentheses below. Inside a ( ) block cmd expands
REM %errorlevel% when the block is PARSED, not when it runs, so a check
REM inside a block reads a stale value. That bug made this script report
REM failure after a perfectly good first-time install. goto-based flow
REM keeps every check reading the live exit code.
set "PY=.venv\Scripts\python.exe"

if exist "%PY%" goto :venv_ready

echo  Creating a local Python environment...
echo  ^(first run only - this may take a few minutes^)
echo.
uv venv
if not errorlevel 1 goto :venv_ready

echo.
echo  ERROR: could not create the Python environment.
echo  The reason is in the messages above - please scroll up.
echo.
pause
exit /b 1

:venv_ready

REM ── Step 3: dependencies ──────────────────────────────────────────────
REM Probe imports instead of trusting a sentinel file. A real import test
REM is the only way to know the venv actually has what we need.
REM Probe imports instead of trusting a sentinel file. A real import test
REM is the only way to know the venv actually has what we need.
"%PY%" -c "import fastapi, uvicorn, numpy, scipy, soundfile, pyloudnorm" 1>nul 2>nul
if not errorlevel 1 goto :deps_ready

echo  Installing audio libraries...
echo  ^(first run only - about 200 MB, a few minutes^)
echo.
REM --python targets this project's venv explicitly. Without it uv infers
REM the environment, which can pick the wrong one (or none) on a machine
REM with other Pythons installed.
uv pip install --python "%PY%" -r requirements.txt

REM Verify by importing rather than trusting the exit code — that is the
REM only thing that proves the environment is actually usable.
"%PY%" -c "import fastapi, uvicorn, numpy, scipy, soundfile, pyloudnorm" 1>nul 2>nul
if not errorlevel 1 goto :deps_installed

echo.
echo  ERROR: the audio libraries did not install correctly.
echo.
echo  The real reason is in the messages above this line - please
echo  scroll up. Common causes are no internet connection, a company
echo  proxy or antivirus blocking downloads, or low disk space.
echo.
echo  To save a log file for a bug report, run this in the same
echo  folder, then attach setup-log.txt to your issue:
echo.
echo      uv pip install --python .venv\Scripts\python.exe -r requirements.txt ^> setup-log.txt 2^>^&1
echo.
echo      https://github.com/henricksmedia/shimmer/issues
echo.
pause
exit /b 1

:deps_installed
echo.
echo  Setup complete. Future launches start in seconds.
echo.

:deps_ready

REM ── Step 4: free the port ─────────────────────────────────────────────
REM Kill any previous Shimmer, then WAIT until the socket is actually
REM released. Stop-Process returns before Windows tears the socket down, so
REM starting immediately used to fail with a cryptic WinError 10048.
REM Written pipe-free and on one line: carets and vertical bars inside a
REM quoted PowerShell string are mangled by cmd's parser.
powershell -NoProfile -Command "$port=%PORT%; $c=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; if($c){Write-Host ' Closing previous session...'; foreach($x in @($c)){try{Stop-Process -Id $x.OwningProcess -Force -ErrorAction Stop}catch{}}}; for($i=0;$i -lt 40;$i++){$b=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; if(-not $b){exit 0}; Start-Sleep -Milliseconds 250}; exit 1"

if %errorlevel% neq 0 (
    echo.
    echo  ERROR: port %PORT% is still in use and could not be freed.
    echo.
    echo  Another program is holding it. To find out which, run:
    echo      netstat -ano ^| findstr :%PORT%
    echo.
    echo  Or start Shimmer on a different port:
    echo      set SHIMMER_PORT=7870 ^&^& start.bat
    echo.
    pause
    exit /b 1
)

REM ── Step 5: start, then open the browser once it actually responds ────
echo  Starting Shimmer...
echo  %URL%
echo.
echo  Leave this window open while you work. Close it to stop Shimmer.
echo.

REM Poll in the background rather than guessing a delay: on a cold start
REM the server can take several seconds to import numpy/scipy, and opening
REM the browser too early lands the user on a connection-error page.
REM
REM Two details matter here:
REM   * No -WindowStyle Hidden. `start /b` already avoids a visible window,
REM     and Hidden makes the browser inherit SW_HIDE so it never appears.
REM   * The URL is opened with cmd's `start`, the standard ShellExecute
REM     path, which reuses the running browser and opens a NEW TAB.
REM The waiter lives in scripts\open-when-ready.ps1 — inline PowerShell in a
REM .bat has to survive two quoting layers and silently breaks.
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-when-ready.ps1" -Url "%URL%/" -Port %PORT%

REM No blind retry here: the port was verified free above, so a failure now
REM is a real error worth reading. Retrying used to silently start a SECOND
REM server whenever the first was stopped, orphaning it on the port.
"%PY%" -m uvicorn shimmer.server:app --host 127.0.0.1 --port %PORT% --log-level warning

echo.
echo  Shimmer has stopped.
pause
