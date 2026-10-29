# Prevents idle sleep while this window is open (does NOT change any power settings). Close the tab / Ctrl-C to release.
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$ES_CONTINUOUS = [uint32]2147483648; $ES_SYSTEM_REQUIRED = [uint32]1
"keeping the system awake (display may still turn off)..."
while ($true) { [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED); Start-Sleep 30 }
