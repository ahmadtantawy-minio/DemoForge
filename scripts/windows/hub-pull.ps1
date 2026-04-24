#Requires -Version 5.1
<#
.SYNOPSIS
  Pull core DemoForge images from GCR (equivalent to scripts/hub-pull.sh).

.EXAMPLE
  pwsh -File scripts/windows/hub-pull.ps1
#>
$ErrorActionPreference = 'Stop'
$PSScriptRoot = if ($MyInvocation.MyCommand.Path) { (Split-Path -Parent $MyInvocation.MyCommand.Path) } elseif ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
. (Join-Path $PSScriptRoot 'DemoForge-Env.ps1')

$ProjectRoot = Get-DemoForgeProjectRoot
$GcrHost = 'gcr.io/minio-demoforge'
$Critical = @(
    'demoforge/demoforge-frontend',
    'demoforge/demoforge-backend',
    'demoforge/data-generator',
    'demoforge/event-processor',
    'demoforge/external-system'
)

$docker = Get-DockerExecutable
if (-not (Test-DockerAvailable)) { exit 1 }

$envHub = Join-Path $ProjectRoot '.env.hub'
$envLocal = Join-Path $ProjectRoot '.env.local'
if (Test-Path $envHub) {
    $h = @{}
    Import-DotEnvFile $envHub $h
    foreach ($kv in $h.GetEnumerator()) { Set-Item -Path "env:$($kv.Key)" -Value $kv.Value }
}
if (Test-Path $envLocal) {
    $h = @{}
    Import-DotEnvFile $envLocal $h
    foreach ($kv in $h.GetEnumerator()) { Set-Item -Path "env:$($kv.Key)" -Value $kv.Value }
}

Write-Host "Pulling core images from GCR:" -ForegroundColor Cyan
Write-Host ''

$pulled = 0
$failed = 0
foreach ($repo in $Critical) {
    $gcrImage = "${GcrHost}/${repo}:latest"
    Write-Host "  Pulling $gcrImage ..." -ForegroundColor Green
    try {
        & $docker @('pull', $gcrImage)
        if ($LASTEXITCODE -ne 0) { throw "pull failed" }
        & $docker @('tag', $gcrImage, "${repo}:latest") 2>$null | Out-Null
        Write-Host "    tagged ${repo}:latest" -ForegroundColor DarkGray
        $pulled++
    }
    catch {
        Write-Host "    failed: $repo" -ForegroundColor Red
        $failed++
    }
}

Write-Host ''
Write-Host "Pulled: $pulled  Failed: $failed" -ForegroundColor $(if ($failed -gt 0) { 'Yellow' } else { 'Green' })
if ($failed -gt 0) { exit 1 }
