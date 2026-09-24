@echo off
setlocal
REM ─────────────────────────────────────────────────────────────────────
REM start-test.bat — try this copy of Shimmer without touching your own.
REM
REM start.bat always runs the latest release, on port 7860, with your
REM settings. This runs whatever copy it sits in (a branch being tested, a
REM worktree), as it is:
REM   - on port 7870, so your everyday Shimmer can stay open beside it
REM   - with its own settings folder, %APPDATA%\Shimmer-test, so nothing
REM     you change here reaches your own settings
REM   - with no update and no branch switch (SHIMMER_NO_UPDATE=1)
REM Everything else is start.bat's own setup, not a copy of it.
REM ─────────────────────────────────────────────────────────────────────

if not defined SHIMMER_PORT set "SHIMMER_PORT=7870"
if not defined SHIMMER_CONFIG_DIR set "SHIMMER_CONFIG_DIR=%APPDATA%\Shimmer-test"
set "SHIMMER_NO_UPDATE=1"

echo.
echo   TEST COPY: %~dp0
echo   Port %SHIMMER_PORT%, settings in %SHIMMER_CONFIG_DIR%
echo.

call "%~dp0start.bat"
