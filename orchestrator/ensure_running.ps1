# Ensures the analysis pipeline supervisor and keep-awake helper are running. Safe to run repeatedly (no-op if both are up).
# Scheduled via Task Scheduler (at logon + every 10 min): task name "MHFZ pipeline watchdog".
$root = 'C:\Users\Ayman\mhfz-60fps\orchestrator'
$py   = 'C:\Users\Ayman\AppData\Local\Programs\Python\Python313\python.exe'
$log  = "$root\watchdog.log"
function Running($pattern) { Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pattern -and $_.ProcessId -ne $PID } }
if (-not (Running 'orchestrator.supervisor\.py')) {
    Start-Process -FilePath $py -ArgumentList '-I', "$root\supervisor.py" -WorkingDirectory $root -WindowStyle Hidden
    Add-Content $log ("{0} started supervisor" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
}
if (-not (Running 'keepawake\.ps1')) {
    Start-Process -FilePath 'pwsh.exe' -ArgumentList '-NoProfile','-WindowStyle','Hidden','-File',"$root\keepawake.ps1" -WindowStyle Hidden
    Add-Content $log ("{0} started keepawake" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
}
