$ErrorActionPreference = 'Stop'
$dataRoot = Join-Path $PSScriptRoot '..\backend\data\postgres'
$pgCtl = Join-Path $env:LOCALAPPDATA 'RaceCore\PostgreSQL\17\pgsql\bin\pg_ctl.exe'

if (-not (Test-Path -LiteralPath $pgCtl)) { throw 'PostgreSQL binaries are missing. Run tools\setup_postgres.ps1 first.' }
if (-not (Test-Path -LiteralPath $dataRoot)) { throw 'PostgreSQL data directory is missing. Run tools\setup_postgres.ps1 first.' }

& $pgCtl -D $dataRoot -l (Join-Path $dataRoot 'server.log') start -w
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to start with exit code $LASTEXITCODE" }
