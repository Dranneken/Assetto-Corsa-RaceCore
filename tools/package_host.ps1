$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendRoot = Join-Path $repositoryRoot 'backend'
$pythonRoot = Join-Path $backendRoot '.venv\Scripts'
$pyinstaller = Join-Path $pythonRoot 'pyinstaller.exe'
$versionText = Get-Content -LiteralPath (Join-Path $backendRoot 'pyproject.toml') -Raw
if ($versionText -notmatch '(?m)^version\s*=\s*"(?<version>[^\"]+)"') {
  throw 'Could not read the RaceCore version from backend\pyproject.toml.'
}
$version = $Matches.version
$appName = "RaceCore-$version"
$distRoot = Join-Path $repositoryRoot 'dist'
$bundleRoot = Join-Path $distRoot 'bundle'
$bundlePath = Join-Path $bundleRoot $appName
$stageRoot = Join-Path $distRoot "$appName-windows-x64"
$archivePath = Join-Path $distRoot "$appName-windows-x64.zip"

if (Test-Path -LiteralPath $archivePath) {
  throw "Package archive already exists: $archivePath. Move or remove it before rebuilding."
}

if (-not (Test-Path -LiteralPath $stageRoot)) {
  if (-not (Test-Path -LiteralPath $pyinstaller)) {
    throw 'PyInstaller is missing. Install backend development dependencies with: python -m pip install -e "backend/[dev]"'
  }

  New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
  $arguments = @(
    '--noconfirm',
    '--clean',
    '--onedir',
    '--console',
    '--contents-directory', '_internal',
    '--name', $appName,
    '--paths', (Join-Path $backendRoot 'src'),
    '--distpath', $bundleRoot,
    '--workpath', (Join-Path $distRoot 'build'),
    '--specpath', (Join-Path $distRoot 'spec'),
    '--collect-all', 'alembic',
    '--collect-all', 'fastapi',
    '--collect-all', 'psycopg',
    '--collect-all', 'psycopg_binary',
    '--collect-all', 'pydantic_settings',
    '--collect-all', 'sqlalchemy',
    '--collect-all', 'uvicorn',
    '--add-data', "$(Join-Path $backendRoot 'migrations');migrations",
    '--add-data', "$(Join-Path $backendRoot 'alembic.ini');.",
    (Join-Path $backendRoot 'src\racecore\launcher.py')
  )

  & $pyinstaller @arguments
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

  New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
  Copy-Item -Path (Join-Path $bundlePath '*') -Destination $stageRoot -Recurse -Force
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install_host.ps1') -Destination (Join-Path $stageRoot 'install_host.ps1')
  New-Item -ItemType Directory -Path (Join-Path $stageRoot 'tools') | Out-Null
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'start_host.ps1') -Destination (Join-Path $stageRoot 'tools')
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'stop_host.ps1') -Destination (Join-Path $stageRoot 'tools')
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'upgrade_host.ps1') -Destination (Join-Path $stageRoot 'tools')
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'view_host_logs.ps1') -Destination (Join-Path $stageRoot 'tools')
  Set-Content -LiteralPath (Join-Path $stageRoot 'version.txt') -Value $version -NoNewline
  @'
RaceCore Windows Host

This user-level package installs the versioned host under:
  %LOCALAPPDATA%\Programs\RaceCore

Runtime configuration and logs are kept separately under:
  %LOCALAPPDATA%\RaceCore

Install from this extracted folder:
  powershell.exe -ExecutionPolicy Bypass -File .\install_host.ps1

Install with PostgreSQL configured through the current RACECORE_DATABASE_URL environment variable:
  powershell.exe -ExecutionPolicy Bypass -File .\install_host.ps1

The host runs on 127.0.0.1 and does not install a Windows service or require administrator rights.
PostgreSQL remains a separate dependency. Use the provided start/stop scripts for host lifecycle,
view_host_logs.ps1 for logs, and upgrade_host.ps1 with a newer package ZIP for upgrades.
'@ | Set-Content -LiteralPath (Join-Path $stageRoot 'INSTALL.txt')
}

$tar = Get-Command tar.exe -ErrorAction SilentlyContinue
if (-not $tar) { throw 'Windows tar.exe is required to create the package ZIP archive.' }
& $tar.Source -a -c -f $archivePath -C $stageRoot .
if ($LASTEXITCODE -ne 0) { throw "Creating the package archive failed with exit code $LASTEXITCODE" }
$checksum = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
Write-Output "Built $appName.exe"
Write-Output "Package: $archivePath"
Write-Output "SHA-256: $checksum"
