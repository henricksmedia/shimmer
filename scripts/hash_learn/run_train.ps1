# Run the trainer and record how it ended. The first detached run of
# train.py vanished with no error, no crash record and no reboot; this
# wrapper writes the start time, the exit code and the end time to a file so
# a second disappearance is not silent.
#
#   powershell -File scripts/hash_learn/run_train.ps1 -Log <dir> [-Epochs 30] [-MaxMinutes 40]
param(
    [string]$Log = "$env:TEMP",
    [int]$Epochs = 30,
    [int]$MaxMinutes = 40,
    [string]$Data = "D:/MusicVault/Tools/Shimmer/hash_data",
    [string]$Out = "scripts/hash_learn/masknet.pt",
    [switch]$Resume
)
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$status = Join-Path $Log "train.status"
$args = @("scripts/hash_learn/train.py", "--data", $Data, "--epochs", $Epochs, "--max-minutes", $MaxMinutes, "--out", $Out)
if ($Resume) { $args += "--resume" }
"start $(Get-Date -Format 'HH:mm:ss') args: $($args -join ' ')" | Out-File -FilePath $status -Encoding utf8
$p = Start-Process -FilePath ".\.venv-stems\Scripts\python.exe" -ArgumentList $args `
    -RedirectStandardOutput (Join-Path $Log "train.log") -RedirectStandardError (Join-Path $Log "train.err") `
    -WindowStyle Hidden -PassThru
"pid $($p.Id)" | Out-File -FilePath $status -Append -Encoding utf8
$p.WaitForExit()
"exit $($p.ExitCode) at $(Get-Date -Format 'HH:mm:ss')" | Out-File -FilePath $status -Append -Encoding utf8
