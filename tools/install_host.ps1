param(
  [string]$DatabaseUrl = $env:RACECORE_DATABASE_URL
)

$ErrorActionPreference = 'Stop'
$packageRoot = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$versionFile = Join-Path $packageRoot 'version.txt'
if (-not (Test-Path -LiteralPath $versionFile)) {
  throw 'version.txt is missing. Extract the complete RaceCore package before installing.'
}
$version = (Get-Content -LiteralPath $versionFile -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$') {
  throw "Invalid package version: $version"
}

$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\RaceCore'
$versionsRoot = Join-Path $installRoot 'versions'
$versionRoot = Join-Path $versionsRoot $version
$appDataRoot = Join-Path $env:LOCALAPPDATA 'RaceCore'
$configFile = Join-Path $appDataRoot '.env'
$currentVersionFile = Join-Path $appDataRoot 'current-version.txt'
$runtimeFile = Join-Path $appDataRoot 'host-runtime.json'
$versionedExe = Join-Path $packageRoot "RaceCore-$version.exe"

if (-not (Test-Path -LiteralPath $versionedExe)) { throw "Packaged executable not found: $versionedExe" }
if (-not (Test-Path -LiteralPath (Join-Path $packageRoot '_internal'))) {
  throw 'The _internal runtime directory is missing. Keep it beside the versioned executable.'
}
if (Test-Path -LiteralPath $versionRoot) {
  throw "RaceCore $version is already installed. Use a new package version for upgrades."
}

New-Item -ItemType Directory -Path $versionsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $appDataRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appDataRoot 'logs') -Force | Out-Null

$previousVersion = $null
if (Test-Path -LiteralPath $currentVersionFile) {
  $previousVersion = (Get-Content -LiteralPath $currentVersionFile -Raw).Trim()
}

if (Test-Path -LiteralPath $runtimeFile) {
  & (Join-Path $PSScriptRoot 'tools\stop_host.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'The current RaceCore host could not be stopped.' }
}

New-Item -ItemType Directory -Path $versionRoot | Out-Null
Copy-Item -LiteralPath $versionedExe -Destination $versionRoot
Copy-Item -LiteralPath (Join-Path $packageRoot '_internal') -Destination $versionRoot -Recurse
if (Test-Path -LiteralPath (Join-Path $packageRoot 'tools')) {
  Copy-Item -LiteralPath (Join-Path $packageRoot 'tools') -Destination $installRoot -Recurse -Force
}
else {
  throw 'Package lifecycle scripts are missing.'
}

$configLines = @()
if (Test-Path -LiteralPath $configFile) { $configLines = @(Get-Content -LiteralPath $configFile) }
if ($DatabaseUrl) {
  $configLines = @($configLines | Where-Object { $_ -notmatch '^RACECORE_DATABASE_URL=' })
  $configLines += "RACECORE_DATABASE_URL=$DatabaseUrl"
}
if (-not ($configLines | Where-Object { $_ -match '^RACECORE_HOST=' })) {
  $configLines += 'RACECORE_HOST=127.0.0.1'
}
if (-not ($configLines | Where-Object { $_ -match '^RACECORE_PORT=' })) {
  $configLines += 'RACECORE_PORT=8000'
}
if (-not ($configLines | Where-Object { $_ -match '^RACECORE_LOG_LEVEL=' })) {
  $configLines += 'RACECORE_LOG_LEVEL=INFO'
}
if (-not ($configLines | Where-Object { $_ -match '^RACECORE_SHUTDOWN_TOKEN=' })) {
  $shutdownToken = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
  $configLines += "RACECORE_SHUTDOWN_TOKEN=$shutdownToken"
}
$adminCredentialsGenerated = $false
if (-not ($configLines | Where-Object { $_ -match '^RACECORE_ADMIN_USERNAME=.+$' })) {
  $configLines = @($configLines | Where-Object { $_ -notmatch '^RACECORE_ADMIN_USERNAME=' })
  $configLines += 'RACECORE_ADMIN_USERNAME=race-admin'
}
if (-not ($configLines | Where-Object { $_ -match '^RACECORE_ADMIN_PASSWORD=.+$' })) {
  $configLines = @($configLines | Where-Object { $_ -notmatch '^RACECORE_ADMIN_PASSWORD=' })
  $adminEntropy = New-Object 'Byte[]' 32
  $adminRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $adminRandom.GetBytes($adminEntropy)
  }
  finally {
    $adminRandom.Dispose()
  }
  $adminPassword = [Convert]::ToBase64String($adminEntropy).TrimEnd('=').Replace('+', '-').Replace('/', '_')
  [Array]::Clear($adminEntropy, 0, $adminEntropy.Length)
  $configLines += "RACECORE_ADMIN_PASSWORD=$adminPassword"
  $adminCredentialsGenerated = $true
}
[System.IO.File]::WriteAllLines($configFile, $configLines, [System.Text.UTF8Encoding]::new($false))

$previousEnvFile = $env:RACECORE_ENV_FILE
$env:RACECORE_ENV_FILE = $configFile
try {
  if ($configLines | Where-Object { $_ -match '^RACECORE_DATABASE_URL=' }) {
    & $versionedExe migrate
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed for RaceCore $version." }
  }

  [System.IO.File]::WriteAllText($currentVersionFile, $version, [System.Text.UTF8Encoding]::new($false))
  & (Join-Path $installRoot 'tools\start_host.ps1')
  if ($LASTEXITCODE -ne 0) { throw "RaceCore $version did not start successfully." }
}
catch {
  if ($previousVersion) {
    [System.IO.File]::WriteAllText($currentVersionFile, $previousVersion, [System.Text.UTF8Encoding]::new($false))
    & (Join-Path $installRoot 'tools\start_host.ps1')
  }
  throw
}
finally {
  $env:RACECORE_ENV_FILE = $previousEnvFile
}

Write-Output "Installed and started RaceCore $version."
Write-Output "App: $versionRoot"
Write-Output "Config and logs: $appDataRoot"
if ($adminCredentialsGenerated) {
  $adminUsername = ($configLines | Where-Object { $_ -match '^RACECORE_ADMIN_USERNAME=' } | Select-Object -Last 1) -replace '^RACECORE_ADMIN_USERNAME=', ''
  Write-Output "Temporary RaceCore admin username: $adminUsername"
  Write-Output "Temporary RaceCore admin password: $adminPassword"
  Write-Output 'Save this password securely. It is shown only when generated.'
}
