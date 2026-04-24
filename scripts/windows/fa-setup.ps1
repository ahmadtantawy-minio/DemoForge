#Requires -Version 5.1
<#
.SYNOPSIS
  Windows-native FA onboarding (equivalent to `make fa-setup` / scripts/fa-setup.sh).

.EXAMPLE
  pwsh -File scripts/windows/fa-setup.ps1
#>
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'DemoForge-Env.ps1')

$ProjectRoot = Get-DemoForgeProjectRoot
$DefaultHubUrl = 'https://demoforge-gateway-64xwtiev6q-ww.a.run.app'
$HubUrl = $DefaultHubUrl

Write-Host ''
Write-Host '  DemoForge — Field setup (Windows)' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-DockerAvailable)) { exit 1 }

$faKey = ''
$envLocal = Join-Path $ProjectRoot '.env.local'
if (Test-Path $envLocal) {
    $h = @{}
    Import-DotEnvFile $envLocal $h
    if ($h['DEMOFORGE_API_KEY']) {
        $faKey = $h['DEMOFORGE_API_KEY'].Trim()
        Write-Host '  Loaded existing FA key from .env.local' -ForegroundColor Green
    }
}

if (-not $faKey) {
    $secure = Read-Host -AsSecureString '  FA Key (from your DemoForge admin)'
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $faKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    Write-Host ''
}

if (-not $faKey) {
    Write-Host '  FA key is required.' -ForegroundColor Red
    exit 1
}

Write-Host '  Checking hub gateway...' -ForegroundColor Cyan
try {
    $null = Invoke-WebRequest -Uri "$HubUrl/health" -UseBasicParsing -TimeoutSec 15
}
catch {
    Write-Host "  Cannot reach $HubUrl — check your network." -ForegroundColor Red
    exit 1
}
Write-Host '  Hub gateway reachable' -ForegroundColor Green

Write-Host ''
Write-Host '  Validating FA key with hub...' -ForegroundColor Cyan
try {
    $bootstrap = Invoke-RestMethod -Uri "$HubUrl/api/hub/fa/bootstrap" -Headers @{ 'X-Api-Key' = $faKey } -Method Get -TimeoutSec 30
}
catch {
    Write-Host '  FA key validation failed. Check your key or ask your admin.' -ForegroundColor Red
    exit 1
}

$faIdFromHub = [string]$bootstrap.fa_id
if ($bootstrap.is_active -eq $false) {
    Write-Host '  Your account is deactivated. Contact your DemoForge admin.' -ForegroundColor Red
    exit 1
}
Write-Host '  FA key validated' -ForegroundColor Green
if ($faIdFromHub) { Write-Host "  Identity from hub: $faIdFromHub" -ForegroundColor Cyan }

$docker = Get-DockerExecutable
$hc = & $docker @('inspect', 'hub-connector') 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host '  Removing legacy hub-connector container...' -ForegroundColor Cyan
    & $docker @('rm', '-f', 'hub-connector') 2>$null | Out-Null
    Write-Host '  Legacy hub-connector removed' -ForegroundColor Green
}

Write-Host ''
Write-Host '  Confirming your identity...' -ForegroundColor Cyan
$faId = $faIdFromHub
if (-not $faId) {
    try {
        $faId = (& git -C $ProjectRoot 'config' 'user.email' 2>$null | Out-String).Trim()
    } catch { }
    if (-not $faId -and (Get-Command gh -ErrorAction SilentlyContinue)) {
        try {
            $ghUser = (& gh api user --jq '.login' 2>$null | Out-String).Trim()
            if ($ghUser) { $faId = $ghUser }
        } catch { }
    }
    if (-not $faId -and (Test-Path $envLocal)) {
        $h2 = @{}
        Import-DotEnvFile $envLocal $h2
        if ($h2['DEMOFORGE_FA_ID']) { $faId = $h2['DEMOFORGE_FA_ID'].Trim() }
    }
}

if ($faId) {
    Write-Host "  Suggested identity: $faId" -ForegroundColor Cyan
    $override = Read-Host '  Press Enter to confirm, or type a different email/username'
    if ($override.Trim()) { $faId = $override.Trim() }
}
else {
    Write-Host '  Could not auto-detect identity.' -ForegroundColor Yellow
    $faId = Read-Host '  Your email or username (e.g. you@company.com)'
}

if (-not $faId) {
    Write-Host '  FA identity is required.' -ForegroundColor Red
    exit 1
}
Write-Host "  FA identity: $faId" -ForegroundColor Green

Write-Host ''
Write-Host '  Registering with DemoForge Hub API...' -ForegroundColor Cyan
$faName = $faId
try {
    $faName = (& git -C $ProjectRoot 'config' 'user.name' 2>$null | Out-String).Trim()
    if (-not $faName) { $faName = $faId }
}
catch { $faName = $faId }

$body = @{ fa_id = $faId; fa_name = $faName; api_key = $faKey } | ConvertTo-Json -Compress
try {
    $reg = Invoke-RestMethod -Uri "$HubUrl/api/hub/fa/register" -Headers @{
        'Content-Type' = 'application/json'
        'X-Api-Key'    = $faKey
    } -Method Post -Body $body -TimeoutSec 30
    if ($reg.fa_id) {
        Write-Host "  Registered as: $($reg.fa_id)" -ForegroundColor Green
    }
    else {
        Write-Host '  Hub registration response unexpected (non-blocking).' -ForegroundColor Yellow
    }
}
catch {
    Write-Host '  Hub registration failed (non-blocking). Check Healthcheck after start.' -ForegroundColor Yellow
}

Set-EnvLocalKey -ProjectRoot $ProjectRoot -Key 'DEMOFORGE_FA_ID' -Value $faId
Set-EnvLocalKey -ProjectRoot $ProjectRoot -Key 'DEMOFORGE_API_KEY' -Value $faKey
Set-EnvLocalKey -ProjectRoot $ProjectRoot -Key 'DEMOFORGE_HUB_URL' -Value $HubUrl
Set-EnvLocalKey -ProjectRoot $ProjectRoot -Key 'DEMOFORGE_MODE' -Value 'fa'

Write-Host ''
Write-Host '  Updated .env.local' -ForegroundColor Green
Write-Host ''
Write-Host '  Setup complete. Next: demoforge-windows.cmd start  (or: pwsh -File scripts/windows/demoforge.ps1 start)' -ForegroundColor Green
Write-Host ''
