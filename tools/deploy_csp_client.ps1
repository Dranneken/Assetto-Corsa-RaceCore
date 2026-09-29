param(
  [Parameter(Mandatory = $true)]
  [string]$AssettoCorsaRoot
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '..\client\csp_lua'
$source = (Resolve-Path -LiteralPath $source).Path
$gameRoot = (Resolve-Path -LiteralPath $AssettoCorsaRoot).Path
$target = Join-Path $gameRoot 'apps\lua\AC_RaceCore'
$targetParent = Split-Path -Parent $target

if (-not (Test-Path -LiteralPath (Join-Path $gameRoot 'apps\lua'))) {
  throw "Assetto Corsa Lua apps directory not found under: $gameRoot"
}

New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse -Force
Write-Output "Deployed RaceCore Client to $target"
