param(
  [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'RaceCore\PostgreSQL\17'),
  [string]$DataRoot = (Join-Path $PSScriptRoot '..\backend\data\postgres')
)

$ErrorActionPreference = 'Stop'
$archive = Join-Path $env:LOCALAPPDATA 'RaceCore\postgresql-17\postgresql.zip'
$downloadUrl = 'https://get.enterprisedb.com/postgresql/postgresql-17.11-4-windows-x64-binaries.zip'
$expectedSha256 = 'B9424EE7BC60B52450FF910A3630225DF32E633F3CB29C1D126D9299D59AEA28'
$bin = Join-Path $InstallRoot 'pgsql\bin'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $root '.env'

if (-not (Test-Path -LiteralPath (Join-Path $bin 'initdb.exe'))) {
  if (-not (Test-Path -LiteralPath $archive)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $archive) -Force | Out-Null
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archive
  }

  $actualSha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
  if ($actualSha256 -ne $expectedSha256) {
    throw "PostgreSQL archive checksum mismatch: $actualSha256"
  }

  $extractRoot = Join-Path $env:TEMP 'racecore-postgresql-17.11-4-extract'
  if (Test-Path -LiteralPath $extractRoot) {
    Remove-Item -LiteralPath $extractRoot -Recurse -Force
  }
  Expand-Archive -LiteralPath $archive -DestinationPath $extractRoot -Force
  $payload = Join-Path $extractRoot 'pgsql'
  if (-not (Test-Path -LiteralPath (Join-Path $payload 'bin\initdb.exe'))) {
    throw 'PostgreSQL archive did not contain the expected pgsql\bin directory.'
  }
  New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
  Move-Item -LiteralPath $payload -Destination (Join-Path $InstallRoot 'pgsql')
  Remove-Item -LiteralPath $extractRoot -Recurse -Force
  Remove-Item -LiteralPath $archive -Force
}

if (-not (Test-Path -LiteralPath (Join-Path $DataRoot 'PG_VERSION'))) {
  New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
  $postgresPassword = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
  $passwordFile = Join-Path $env:TEMP "racecore-postgres-password-$([guid]::NewGuid().ToString('N')).txt"
  try {
    [System.IO.File]::WriteAllText($passwordFile, $postgresPassword)
    & (Join-Path $bin 'initdb.exe') -D $DataRoot -U postgres --encoding=UTF8 --auth=scram-sha-256 --pwfile=$passwordFile
    if ($LASTEXITCODE -ne 0) { throw "initdb failed with exit code $LASTEXITCODE" }
  }
  finally {
    Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
  }

  $postgresPassword | Set-Content -LiteralPath (Join-Path $DataRoot 'racecore-superuser-password.txt') -NoNewline
  & (Join-Path $bin 'pg_ctl.exe') -D $DataRoot -l (Join-Path $DataRoot 'server.log') start -w
  if ($LASTEXITCODE -ne 0) { throw "pg_ctl start failed with exit code $LASTEXITCODE" }

  $racecorePassword = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
  $env:PGPASSWORD = $postgresPassword
  try {
    & (Join-Path $bin 'psql.exe') -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE racecore LOGIN PASSWORD '$racecorePassword'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the RaceCore PostgreSQL role.' }
    & (Join-Path $bin 'createdb.exe') -h 127.0.0.1 -U postgres -O racecore racecore
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the RaceCore database.' }
  }
  finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
  }

  $connection = "postgresql+psycopg://racecore:$racecorePassword@127.0.0.1:5432/racecore"
  $lines = @()
  if (Test-Path -LiteralPath $envFile) { $lines = @(Get-Content -LiteralPath $envFile) }
  $lines = @($lines | Where-Object { $_ -notmatch '^RACECORE_DATABASE_URL=' })
  $lines += "RACECORE_DATABASE_URL=$connection"
  [System.IO.File]::WriteAllLines($envFile, $lines, [System.Text.UTF8Encoding]::new($false))
  Write-Output "Configured PostgreSQL data at $DataRoot and wrote the local connection URL to .env."
}
else {
  Write-Output "PostgreSQL data already exists at $DataRoot; no database changes were made."
}

Write-Output "PostgreSQL binaries: $bin"
Write-Output "Start: powershell -ExecutionPolicy Bypass -File .\tools\start_postgres.ps1"
Write-Output "Stop:  powershell -ExecutionPolicy Bypass -File .\tools\stop_postgres.ps1"
