<#
    open-when-ready.ps1 — wait for the Shimmer server, then open a browser tab.

    Called in the background by start.bat. This lives in its
    own file because embedding the same logic inline in a .bat means fighting
    two layers of quoting (cmd, then PowerShell), which silently mangles
    pipes, quotes and carets.

    Readiness is checked with a raw TCP connect rather than Invoke-WebRequest:
    IWR carries proxy detection and HttpClient startup overhead that can blow
    past a short timeout even when the server is answering fine, which made an
    earlier version give up and never open the browser at all.

    Usage:
        powershell -NoProfile -ExecutionPolicy Bypass `
            -File scripts\open-when-ready.ps1 -Url http://localhost:7860/ -Port 7860
#>
param(
    [Parameter(Mandatory = $true)][string] $Url,
    [Parameter(Mandatory = $true)][int]    $Port,
    [int] $TimeoutSeconds = 60
)

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

while ((Get-Date) -lt $deadline) {
    $listening = $false
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async  = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if ($async.AsyncWaitHandle.WaitOne(1000)) {
            $client.EndConnect($async)
            $listening = $true
        }
        $client.Close()
    } catch {
        $listening = $false
    }

    if ($listening) {
        # Hand the URL to the shell so it opens in the user's default browser,
        # reusing an already-open window as a NEW TAB. cmd's `start` is used
        # rather than `Start-Process $Url` because it goes through ShellExecute
        # with the correct desktop association even when this script was
        # launched detached from a console. The empty "" is the window title
        # argument — without it, `start` swallows the URL as the title.
        Start-Process -FilePath 'cmd.exe' `
                      -ArgumentList '/c', 'start', '""', $Url `
                      -WindowStyle Hidden
        exit 0
    }

    Start-Sleep -Milliseconds 400
}

# Server never came up in time; the launcher prints its own diagnostics.
exit 1
