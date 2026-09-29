$ErrorActionPreference = 'Stop'
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\RaceCore'
$appDataRoot = Join-Path $env:LOCALAPPDATA 'RaceCore'
$configFile = Join-Path $appDataRoot '.env'
$runtimeFile = Join-Path $appDataRoot 'host-runtime.json'

if (-not (Test-Path -LiteralPath $runtimeFile)) {
  Write-Output 'RaceCore is not running.'
  return
}

$runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($runtime.pid)" -ErrorAction SilentlyContinue
if (-not $process) {
  Remove-Item -LiteralPath $runtimeFile -Force
  Write-Output 'Removed stale RaceCore process record.'
  return
}

$recordedExe = [IO.Path]::GetFullPath([string]$runtime.executable)
$runningExe = [IO.Path]::GetFullPath([string]$process.ExecutablePath)
if ($recordedExe -ne $runningExe -or -not $runningExe.StartsWith($installRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'The recorded RaceCore PID does not point to the installed RaceCore executable.'
}

$shutdownToken = $null
foreach ($line in Get-Content -LiteralPath $configFile) {
  if ($line -match '^RACECORE_SHUTDOWN_TOKEN=(.*)$') { $shutdownToken = $Matches[1] }
}
if (-not $shutdownToken) { throw 'The RaceCore shutdown token is missing from the local configuration.' }

try {
  Invoke-RestMethod -Uri "http://127.0.0.1:$($runtime.port)/api/v1/system/shutdown" `
    -Method Post -Headers @{ 'X-RaceCore-Shutdown-Token' = $shutdownToken } -TimeoutSec 3 | Out-Null
}
catch {
  # Fall back to a process stop if the health endpoint is no longer responding.
}

$stopped = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
  Start-Sleep -Milliseconds 500
  if (-not (Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue)) { $stopped = $true; break }
}
if (-not $stopped) {
  Stop-Process -Id $runtime.pid -Force
  Start-Sleep -Milliseconds 300
}

Remove-Item -LiteralPath $runtimeFile -Force -ErrorAction SilentlyContinue
Write-Output 'RaceCore stopped.'
