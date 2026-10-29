# Stops any running hub.py / feeder.py python processes (not the supervisor loops).
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'hub\.py|feeder\.py' } |
    ForEach-Object { "stopping $($_.ProcessId): $($_.CommandLine)"; Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" |
    Where-Object { $_.CommandLine -match '11435:127\.0\.0\.1:11434' } |
    ForEach-Object { "stopping old tunnel $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'supervisor\.py' } |
    ForEach-Object { "stopping supervisor $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
