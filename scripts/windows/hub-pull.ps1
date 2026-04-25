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

try {
    $null = Invoke-WebRequest -Uri 'https://gcr.io/v2/' -UseBasicParsing -TimeoutSec 10
    Write-Host 'HTTPS to https://gcr.io/v2/ from Windows: ok (TLS path).' -ForegroundColor DarkGray
}
catch {
    Write-Host 'HTTPS to gcr.io from Windows failed (proxy?). Docker engine may still pull if its DNS differs.' -ForegroundColor Yellow
}

function Write-DockerEngineGcrDnsProbe {
    param([Parameter(Mandatory)][string]$Engine)
    $probeImg = 'alpine:3.19'
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Engine @('pull', $probeImg) 2>&1 | Out-Null
    }
    finally {
        $ErrorActionPreference = $savedEap
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Skipping in-container DNS probe (could not pull alpine:3.19; docker.io may be blocked from the engine).' -ForegroundColor Yellow
        return
    }
    $okDefault = (Invoke-DockerNativeQuiet -Engine $Engine -ArgumentList @('run', '--rm', $probeImg, 'nslookup', 'gcr.io')) -eq 0
    if ($okDefault) {
        Write-Host 'Docker engine DNS probe: gcr.io resolves inside a container (matches or exceeds host DNS).' -ForegroundColor DarkGray
        return
    }
    $okExplicit = (Invoke-DockerNativeQuiet -Engine $Engine -ArgumentList @('run', '--rm', '--dns', '8.8.8.8', '--dns', '8.8.4.4', $probeImg, 'nslookup', 'gcr.io')) -eq 0
    if ($okExplicit) {
        Write-Host 'Docker engine default DNS failed gcr.io, but a container with --dns 8.8.8.8 worked.' -ForegroundColor Yellow
        Write-Host 'Fix: Docker Desktop > Settings > Docker Engine > add "dns": ["8.8.8.8","8.8.4.4"], Apply & Restart.' -ForegroundColor Yellow
    }
    else {
        Write-Host 'Docker engine still cannot resolve gcr.io in a test container. Image refs are gcr.io/minio-demoforge/demoforge/... (same as hub-push.sh); this is engine DNS/VPN/firewall, not a wrong image name.' -ForegroundColor Yellow
    }
}

Write-DockerEngineGcrDnsProbe -Engine $docker

Write-Host "First pull target (sanity, matches hub-push): ${GcrHost}/demoforge/demoforge-frontend:latest" -ForegroundColor DarkGray
Write-Host 'Each docker pull uses the manifest for this engine CPU (amd64 vs arm64); no --platform needed.' -ForegroundColor DarkGray
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
