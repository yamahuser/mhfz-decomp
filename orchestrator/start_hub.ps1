# Starts the hub hidden in the background (no-op if already running).
$dir = $PSScriptRoot
if (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'hub\.py' }) { "hub already running"; return }
Start-Process python -ArgumentList "-I","$dir\hub.py" -WorkingDirectory $dir -WindowStyle Hidden
"hub started"
