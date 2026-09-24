# update-to-latest.ps1 - keep a git copy of Shimmer on the latest release.
#
# start.bat runs this before anything else, so the everyday copy always
# starts on the newest version on GitHub's main branch. It only ever moves
# forward along main (a fast-forward), and it never touches a copy with
# unsaved changes. A copy downloaded as a zip has no .git folder and is
# left alone, and so is any copy when the network is down.
#
# Exit codes, read by start.bat:
#   0   nothing to do, or it could not check: start as it is
#   10  the copy was updated: start.bat starts again from the new files
#
# Set SHIMMER_NO_UPDATE=1 to skip it (start-test.bat does, so a test copy
# stays on the branch being tested).
param([string]$Folder = (Split-Path -Parent $PSScriptRoot))

if ($env:SHIMMER_NO_UPDATE -eq '1' -or $env:SHIMMER_UPDATED -eq '1') { exit 0 }
if (-not (Test-Path (Join-Path $Folder '.git'))) { exit 0 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { exit 0 }

Set-Location $Folder
function Invoke-Git([string[]]$a) { $out = & git.exe @a 2>$null; return ,@($out) }

$branch = (Invoke-Git @('rev-parse', '--abbrev-ref', 'HEAD'))[0]
$switched = $false
# Untracked files (a scratch file, a log) do not block an update; changed
# tracked files do.
$dirty = (Invoke-Git @('status', '--porcelain', '--untracked-files=no')).Count -gt 0

if ($branch -ne 'main') {
    Write-Host ''
    Write-Host "  This copy is on the branch '$branch', not on the latest release (main)."
    Write-Host '  start.bat runs the latest release. To try a branch, use start-test.bat.'
    if ($dirty) {
        Write-Host '  It has unsaved changes, so it is left as it is.'
        Write-Host ''
        exit 0
    }
    $answer = Read-Host '  Switch to the latest release now? [Y/n]'
    if ($answer -match '^[nN]') { Write-Host ''; exit 0 }
    & git checkout -q main 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  Could not switch to main. Starting as it is.'
        exit 0
    }
    $branch = 'main'
    $switched = $true
}
# After a switch the files on disk changed, so start.bat must start again.
$restart = $(if ($switched) { 10 } else { 0 })

$before = (Invoke-Git @('rev-parse', 'HEAD'))[0]
$job = Start-Job { param($f) Set-Location $f; git fetch -q origin main 2>$null; $LASTEXITCODE } -ArgumentList $Folder
if (-not (Wait-Job $job -Timeout 20) -or (Receive-Job $job) -ne 0) {
    Remove-Job $job -Force
    Write-Host '  Could not check for updates (offline?). Starting the version you have.'
    exit $restart
}
Remove-Job $job -Force

$latest = (Invoke-Git @('rev-parse', 'origin/main'))[0]
if ($latest -eq $before) { exit $restart }
if ($dirty) {
    Write-Host '  A newer version is out, but this copy has unsaved changes, so it is not updated.'
    exit $restart
}
& git merge -q --ff-only origin/main 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '  A newer version is out, but this copy has moved away from it. Starting as it is.'
    exit $restart
}
$version = (Select-String -Path 'shimmer\__init__.py' -Pattern '__version__ = "(.+)"').Matches.Groups[1].Value
Write-Host "  Updated to Shimmer $version."
exit 10
