@echo off
setlocal EnableExtensions
title Shimmer - Push to GitHub
color 05

echo.
echo  ========================================
echo       SHIMMER - Push to GitHub
echo       https://github.com/henricksmedia/shimmer
echo  ========================================
echo.

cd /d "%~dp0"

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo  Git was not found on PATH.
    echo  Install from: https://git-scm.com/download/win
    pause
    exit /b 1
)

REM Ensure origin points at the Shimmer repo
set "REMOTE_URL=https://github.com/henricksmedia/shimmer.git"
for /f "delims=" %%r in ('git remote get-url origin 2^>nul') do set "CURRENT_REMOTE=%%r"
if not defined CURRENT_REMOTE (
    echo  Adding remote "origin" ...
    git remote add origin "%REMOTE_URL%"
    if %errorlevel% neq 0 (
        echo  Failed to add remote.
        pause
        exit /b 1
    )
) else (
    echo %CURRENT_REMOTE% | findstr /i "henricksmedia/shimmer" >nul
    if %errorlevel% neq 0 (
        echo  Remote origin is: %CURRENT_REMOTE%
        echo  Expected:         %REMOTE_URL%
        set /p "FIX_REMOTE=Update origin to the Shimmer repo? [Y/N]: "
        if /i "%FIX_REMOTE%"=="Y" goto fix_remote
        echo  Aborted.
        pause
        exit /b 1
    )
)
goto after_remote

:fix_remote
git remote set-url origin "%REMOTE_URL%"

:after_remote
for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "BRANCH=%%b"
if not defined BRANCH (
    echo  Not a git repository.
    pause
    exit /b 1
)

echo  Branch: %BRANCH%
echo.
for /f "delims=" %%d in ('git log -1 --format="%%ci" 2^>nul') do set "LAST_COMMIT=%%d"
echo  Last commit on this machine: %LAST_COMMIT%
echo  GitHub will stay stale until you commit and push new work.
echo.
echo  --- Uncommitted changes ---
git status --short
echo.

set "HAS_CHANGES=0"
git diff --quiet 2>nul
if %errorlevel% neq 0 set "HAS_CHANGES=1"
git diff --cached --quiet 2>nul
if %errorlevel% neq 0 set "HAS_CHANGES=1"
for /f "delims=" %%f in ('git ls-files --others --exclude-standard 2^>nul') do set "HAS_CHANGES=1"

set "COMMIT_MSG="
if "%HAS_CHANGES%"=="1" goto prompt_required
set /p "COMMIT_MSG=Commit message (leave blank to push existing commits only): "
goto after_prompt

:prompt_required
echo  You have uncommitted changes. A commit message is required
echo  to publish them - leaving it blank will NOT update GitHub.
echo.
set /p "COMMIT_MSG=Commit message: "
if "%COMMIT_MSG%"=="" goto no_commit_msg
goto after_prompt

:no_commit_msg
echo.
echo  No commit message - nothing will be published.
pause
exit /b 1

:after_prompt
if "%COMMIT_MSG%"=="" goto do_push

echo.
echo  Staging changes...
git add -A
if %errorlevel% neq 0 (
    echo  git add failed.
    pause
    exit /b 1
)

echo  Committing...
git commit -m "%COMMIT_MSG%"
if %errorlevel% neq 0 (
    echo  Commit failed.
    pause
    exit /b 1
)
echo  Committed.
echo.

:do_push
echo  Pushing to origin/%BRANCH% ...
git push -u origin %BRANCH%
if %errorlevel% neq 0 (
    echo.
    echo  Push failed.
    echo  If authentication failed, sign in with GitHub CLI:
    echo    winget install GitHub.cli
    echo    gh auth login
    echo  Or configure a credential helper / personal access token for HTTPS.
    pause
    exit /b 1
)

echo.
echo  Push complete - GitHub should now show today's date.
echo  https://github.com/henricksmedia/shimmer
echo.
pause
exit /b 0
