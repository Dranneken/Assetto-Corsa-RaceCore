$ErrorActionPreference = 'Stop'
$dataRoot = Join-Path $PSScriptRoot '..\backend\data\postgres'
$pgCtl = Join-Path $env:LOCALAPPDATA 'RaceCore\PostgreSQL\17\pgsql\bin\pg_ctl.exe'

if (-not (Test-Path -LiteralPath $pgCtl)) { throw 'PostgreSQL binaries are missing.' }
if (-not (Test-Path -LiteralPath $dataRoot)) { throw 'PostgreSQL data directory is missing.' }

& $pgCtl -D $dataRoot stop -m fast -w
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to stop with exit code $LASTEXITCODE" }
