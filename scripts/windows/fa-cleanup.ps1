#Requires -Version 5.1
<#
.SYNOPSIS
  Remove .env.local after backup (equivalent to make fa-cleanup).
#>
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'DemoForge-Env.ps1')
$root = Get-DemoForgeProjectRoot
$envLocal = Join-Path $root '.env.local'
if (Test-Path $envLocal) {
    Copy-Item $envLocal "$envLocal.bak" -Force
    Write-Host "Backed up .env.local -> .env.local.bak" -ForegroundColor Green
    Remove-Item $envLocal -Force
    Write-Host 'Removed .env.local' -ForegroundColor Green
}
else {
    Write-Host '.env.local not found (nothing to remove)' -ForegroundColor Yellow
}
$sim = Join-Path $root '.env.sim'
if (Test-Path $sim) { Remove-Item $sim -Force }
Write-Host ''
Write-Host 'Run fa-setup.ps1 to reconfigure.' -ForegroundColor Cyan
