param([int]$Tail = 80)

$ErrorActionPreference = 'Stop'
$appDataRoot = Join-Path $env:LOCALAPPDATA 'RaceCore'
$runtimeFile = Join-Path $appDataRoot 'host-runtime.json'
if (Test-Path -LiteralPath $runtimeFile) {
  $runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
  foreach ($log in @($runtime.stdout_log, $runtime.stderr_log)) {
    if (Test-Path -LiteralPath $log) {
      Write-Output "--- $log ---"
      Get-Content -LiteralPath $log -Tail $Tail
    }
  }
  return
}

$latestLogs = Get-ChildItem -LiteralPath (Join-Path $appDataRoot 'logs') -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 2
foreach ($log in $latestLogs) {
  Write-Output "--- $($log.FullName) ---"
  Get-Content -LiteralPath $log.FullName -Tail $Tail
}
