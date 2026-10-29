# Usage: loop_service.ps1 hub|feeder|tunnel   -- restarts the service 5 s after any crash/exit.
param([string]$Service)
Set-Location $PSScriptRoot
while ($true) {
    switch ($Service) {
        'hub'    { python -I hub.py }
        'feeder' { python -I feeder.py }
        'tunnel' { ssh -N -L 11435:127.0.0.1:11434 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -o BatchMode=yes -i "$env:USERPROFILE\.ssh\marble_ed25519" ayman@192.168.1.240 }
    }
    "$(Get-Date -Format s) $Service exited; restarting in 5s" | Out-File -Append "$PSScriptRoot\supervisor.log"
    Start-Sleep 5
}
