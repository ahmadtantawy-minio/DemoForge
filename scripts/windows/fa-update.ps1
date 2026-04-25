#Requires -Version 5.1
<#
.SYNOPSIS
  Windows FA day-to-day update: hub-pull, restart, template sync + license cache (scripts/fa-update.sh parity).
  For git pull + re-run on script changes, use demoforge-update.ps1 or make fa-update-win.

.EXAMPLE
  pwsh -File scripts/windows/fa-update.ps1
#>
$ErrorActionPreference = 'Stop'
$PSScriptRoot = if ($MyInvocation.MyCommand.Path) { (Split-Path -Parent $MyInvocation.MyCommand.Path) } elseif ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
. (Join-Path $PSScriptRoot 'DemoForge-Env.ps1')

$ProjectRoot = Get-DemoForgeProjectRoot
$DefaultHubUrl = 'https://demoforge-gateway-64xwtiev6q-ww.a.run.app'
$BackendPort = '9210'

Write-Host 'DemoForge - update (Windows)' -ForegroundColor Green
Write-Host ''

$envLocal = Join-Path $ProjectRoot '.env.local'
$faKey = ''
if (Test-Path $envLocal) {
    $h = @{}
    Import-DotEnvFile $envLocal $h
    if ($h['DEMOFORGE_API_KEY']) { $faKey = $h['DEMOFORGE_API_KEY'].Trim() }
}

$faValid = $false
if (-not $faKey) {
    Write-Host 'FA key not in .env.local - run fa-setup.ps1. Skipping hub auth steps.' -ForegroundColor Yellow
}
else {
    $hubUrl = $DefaultHubUrl
    try {
        $null = Invoke-WebRequest -Uri "$hubUrl/health" -UseBasicParsing -TimeoutSec 5
        Write-Host 'Hub reachable' -ForegroundColor Green
    }
    catch {
        Write-Error "Hub gateway unreachable. Check your network."
        exit 1
    }
    try {
        $r = Invoke-WebRequest -Uri "$hubUrl/api/hub/fa/bootstrap" -Headers @{ 'X-Api-Key' = $faKey } -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) {
            Write-Host 'FA key accepted (bootstrap)' -ForegroundColor Green
            $faValid = $true
        }
    }
    catch {
        Write-Host 'FA key rejected or hub error - skipping sync after restart.' -ForegroundColor Yellow
    }
}

$pullRc = Invoke-DfScriptFile -Path (Join-Path $PSScriptRoot 'hub-pull.ps1')
if ($pullRc -ne 0) {
    Write-Host 'hub-pull reported failures - continuing with restart.' -ForegroundColor Yellow
}

Set-EnvLocalKey -ProjectRoot $ProjectRoot -Key 'DEMOFORGE_MODE' -Value 'fa'
Set-EnvLocalKey -ProjectRoot $ProjectRoot -Key 'DEMOFORGE_HUB_URL' -Value $DefaultHubUrl

$docker = Get-DockerExecutable
if ((Invoke-DockerNativeQuiet -Engine $docker -ArgumentList @('inspect', 'hub-connector')) -eq 0) {
    $null = Invoke-DockerNativeQuiet -Engine $docker -ArgumentList @('rm', '-f', 'hub-connector')
}

$restartRc = Invoke-DfScriptFile -Path (Join-Path $PSScriptRoot 'demoforge.ps1') -Arguments @('restart')
if ($restartRc -ne 0) { exit $restartRc }

Write-Host 'Waiting for backend...' -ForegroundColor Green
$ready = $false
for ($i = 0; $i -lt 12; $i++) {
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:${BackendPort}/api/health" -TimeoutSec 3
        if ($h.status) {
            $ready = $true
            break
        }
    }
    catch { }
    Start-Sleep -Seconds 5
}

if (-not $ready) {
    Write-Host 'Backend not ready after 60s - skipping template sync.' -ForegroundColor Yellow
    exit 0
}

if ($faValid) {
    Write-Host 'Syncing templates...' -ForegroundColor Green
    try {
        $sync = Invoke-RestMethod -Uri "http://127.0.0.1:${BackendPort}/api/templates/sync" -Method Post -TimeoutSec 35
        if ($sync.status -eq 'ok') {
            Write-Host "Templates synced: $($sync.downloaded) downloaded, $($sync.unchanged) unchanged" -ForegroundColor Green
        }
        else {
            Write-Host "Template sync: $($sync | ConvertTo-Json -Compress)" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "Template sync failed: $_" -ForegroundColor Yellow
    }

    Write-Host 'Caching license keys...' -ForegroundColor Green
    try {
        $lic = Invoke-RestMethod -Uri "http://127.0.0.1:${BackendPort}/api/fa/licenses/cache" -TimeoutSec 20
        Write-Host ($lic | ConvertTo-Json -Compress) -ForegroundColor DarkGray
    }
    catch {
        Write-Host "License cache skipped: $_" -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host 'Update complete.' -ForegroundColor Green
