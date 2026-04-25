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

# Must match scripts/hub-push.sh tag: <GCR_HOST>/demoforge/<component>:latest (after .env so DEMOFORGE_GCR_HOST applies)
$GcrHost = if ($env:DEMOFORGE_GCR_HOST -and $env:DEMOFORGE_GCR_HOST.Trim()) {
    $env:DEMOFORGE_GCR_HOST.Trim().TrimEnd('/')
} else {
    'gcr.io/minio-demoforge'
}

function Test-HostnameResolves {
    param([Parameter(Mandatory)][string]$Name)
    try {
        $null = [System.Net.Dns]::GetHostAddresses($Name)
        return $true
    }
    catch {
        return $false
    }
}

Write-Host "Pulling core images from GCR ($GcrHost):" -ForegroundColor Cyan
Write-Host ''

if (-not (Test-HostnameResolves 'gcr.io')) {
    Write-Host 'DNS: cannot resolve gcr.io from this host. The pull URL is still gcr.io/minio-demoforge/demoforge/... (same as hub-push.sh).' -ForegroundColor Red
    Write-Host 'Fix: corporate DNS/VPN, or Docker Desktop > Settings > Docker Engine > add "dns": ["8.8.8.8","8.8.4.4"], Apply & Restart.' -ForegroundColor Yellow
    Write-Host 'Override registry root only if your team published elsewhere: $env:DEMOFORGE_GCR_HOST = "gcr.io/minio-demoforge"' -ForegroundColor Yellow
    exit 1
}
if (-not (Test-HostnameResolves 'registry-1.docker.io')) {
    Write-Host 'Warning: cannot resolve registry-1.docker.io (Docker Hub). Base layers may fail unless cached.' -ForegroundColor Yellow
}

Write-Host ''

$pulled = 0
$failed = 0
foreach ($repo in $Critical) {
    $gcrImage = "${GcrHost}/${repo}:latest"
    Write-Host "  Pulling $gcrImage ..." -ForegroundColor Green
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $docker @('pull', $gcrImage)
        $pullOk = ($LASTEXITCODE -eq 0)
        if ($pullOk) {
            $null = Invoke-DockerNativeQuiet -Engine $docker -ArgumentList @('tag', $gcrImage, "${repo}:latest")
            Write-Host "    tagged ${repo}:latest" -ForegroundColor DarkGray
            $pulled++
        }
        else {
            Write-Host "    failed: $repo (docker exit $LASTEXITCODE)" -ForegroundColor Red
            $failed++
        }
    }
    finally {
        $ErrorActionPreference = $savedEap
    }
}

Write-Host ''
Write-Host "Pulled: $pulled  Failed: $failed" -ForegroundColor $(if ($failed -gt 0) { 'Yellow' } else { 'Green' })
if ($failed -gt 0) { exit 1 }
