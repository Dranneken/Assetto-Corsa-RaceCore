$ErrorActionPreference = 'Stop'
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\RaceCore'
$appDataRoot = Join-Path $env:LOCALAPPDATA 'RaceCore'
$configFile = Join-Path $appDataRoot '.env'
$currentVersionFile = Join-Path $appDataRoot 'current-version.txt'
$runtimeFile = Join-Path $appDataRoot 'host-runtime.json'

if (-not (Test-Path -LiteralPath $currentVersionFile)) { throw 'RaceCore is not installed. Run install_host.ps1 first.' }
if (-not (Test-Path -LiteralPath $configFile)) { throw 'RaceCore configuration is missing.' }
$version = (Get-Content -LiteralPath $currentVersionFile -Raw).Trim()
$exePath = Join-Path $installRoot "versions\$version\RaceCore-$version.exe"
if (-not (Test-Path -LiteralPath $exePath)) { throw "RaceCore executable not found: $exePath" }

$existingRuntime = $null
if (Test-Path -LiteralPath $runtimeFile) {
  $existingRuntime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
}
if ($existingRuntime -and (Get-Process -Id $existingRuntime.pid -ErrorAction SilentlyContinue)) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($existingRuntime.port)/health" -TimeoutSec 2
    if ($health.service -eq 'racecore') { throw 'RaceCore is already running.' }
  }
  catch {
    if ($_.Exception.Message -eq 'RaceCore is already running.') { throw }
  }
}

$port = 8000
foreach ($line in Get-Content -LiteralPath $configFile) {
  if ($line -match '^RACECORE_PORT\s*=\s*(\d+)\s*$') { $port = [int]$Matches[1] }
}
$logRoot = Join-Path $appDataRoot 'logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutLog = Join-Path $logRoot "host-$timestamp.stdout.log"
$stderrLog = Join-Path $logRoot "host-$timestamp.stderr.log"

$previousEnvFile = $env:RACECORE_ENV_FILE
$env:RACECORE_ENV_FILE = $configFile
try {
  $process = Start-Process -FilePath $exePath -ArgumentList 'run' -WorkingDirectory $appDataRoot `
    -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
}
finally {
  $env:RACECORE_ENV_FILE = $previousEnvFile
}

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
  Start-Sleep -Milliseconds 500
  if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) { break }
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
    if ($health.service -eq 'racecore') { $ready = $true; break }
  }
  catch {
    # The host may still be starting or the port may belong to a different local process.
  }
}

if (-not $ready) {
  Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  throw "RaceCore did not become healthy on 127.0.0.1:$port. Check $stdoutLog and $stderrLog."
}

$runtime = [ordered]@{
  pid = $process.Id
  port = $port
  executable = $exePath
  stdout_log = $stdoutLog
  stderr_log = $stderrLog
  started_at = (Get-Date).ToUniversalTime().ToString('o')
}
[System.IO.File]::WriteAllText($runtimeFile, ($runtime | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
Write-Output "RaceCore is healthy at http://127.0.0.1:$port/health (PID $($process.Id))."
Write-Output "Logs: $logRoot"
