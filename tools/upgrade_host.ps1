param(
  [Parameter(Mandatory = $true)]
  [string]$PackagePath
)

$ErrorActionPreference = 'Stop'
$packagePathResolved = (Resolve-Path -LiteralPath $PackagePath).Path
if ([IO.Path]::GetExtension($packagePathResolved) -ne '.zip') {
  throw 'PackagePath must be a RaceCore Windows package ZIP.'
}

$upgradeRoot = Join-Path $env:TEMP "racecore-upgrade-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $upgradeRoot | Out-Null
try {
  Expand-Archive -LiteralPath $packagePathResolved -DestinationPath $upgradeRoot
  & (Join-Path $upgradeRoot 'install_host.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'The new RaceCore package did not install successfully.' }
}
finally {
  Remove-Item -LiteralPath $upgradeRoot -Recurse -Force -ErrorAction SilentlyContinue
}
