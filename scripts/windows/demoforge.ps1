#Requires -Version 5.1
<#
.SYNOPSIS
  Windows-native DemoForge lifecycle (subset of demoforge.sh): start, stop, restart, status, logs.

.EXAMPLE
  pwsh -File scripts/windows/demoforge.ps1 start
  pwsh -File scripts/windows/demoforge.ps1 restart
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'help')]
    [string]$Command = 'help'
)

$ErrorActionPreference = 'Stop'
$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $PSScriptRoot 'DemoForge-Env.ps1')

$ProjectRoot = Get-DemoForgeProjectRoot
$docker = Get-DockerExecutable

function Write-DfLog($msg, $color = 'Blue') {
    Write-Host "[DemoForge] $msg" -ForegroundColor $color
}

function Invoke-Compose {
    param([string[]]$ExtraArgs)
    Push-Location $ProjectRoot
    try {
        $argv = @((Get-ComposeArgs $ProjectRoot) + $ExtraArgs)
        & $docker @argv
        if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { return $LASTEXITCODE }
        return 0
    }
    finally {
        Pop-Location
    }
}

function Stop-CoreServices {
    Apply-DemoForgeEnvironment -ProjectRoot $ProjectRoot
    $null = Invoke-Compose @('down', '--remove-orphans')
    $names = @((& $docker @('ps', '--format', '{{.Names}}') 2>$null) -split "`n" | Where-Object { $_ })
    $faCoreRunning = $names | Where-Object { $_ -match '^demoforge-(backend|frontend)-\d+$' }
    $demoIds = @((& $docker @('ps', '-aq', '--filter', 'label=demoforge.demo') 2>$null) -split "`n" | Where-Object { $_ })
    if ($demoIds.Count -gt 0 -and -not $faCoreRunning) {
        foreach ($id in $demoIds) {
            & $docker @('stop', $id) 2>$null | Out-Null
            & $docker @('rm', $id) 2>$null | Out-Null
        }
    }
}

function Wait-Http {
    param([string]$Url, [string]$Name, [int]$MaxSeconds = 60)
    $elapsed = 0
    Write-DfLog "Waiting for $Name ..."
    while ($elapsed -lt $MaxSeconds) {
        try {
            $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            Write-DfLog "$Name is ready (${elapsed}s)" 'Green'
            return $true
        }
        catch { }
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
    Write-DfLog "$Name did not respond within ${MaxSeconds}s. Try: demoforge-windows.cmd logs" 'Yellow'
    return $false
}

function Start-DemoForgeCore {
    if (-not (Test-DockerAvailable)) { exit 1 }

    Apply-DemoForgeEnvironment -ProjectRoot $ProjectRoot

    if ($env:DEMOFORGE_MODE -ne 'dev') {
        if (-not $env:DEMOFORGE_FA_ID) {
            Write-Host '  FA identity not configured. Run: pwsh -File scripts/windows/fa-setup.ps1' -ForegroundColor Red
            exit 1
        }
        Write-Host "  FA: $($env:DEMOFORGE_FA_ID)" -ForegroundColor Cyan
    }

    if ($env:DEMOFORGE_MODE -ne 'dev') {
        $hub = if ($env:DEMOFORGE_HUB_URL) { $env:DEMOFORGE_HUB_URL } else { 'https://demoforge-gateway-64xwtiev6q-ww.a.run.app' }
        Write-DfLog 'Checking hub connectivity...'
        try {
            $null = Invoke-WebRequest -Uri "$hub/health" -UseBasicParsing -TimeoutSec 5
            Write-DfLog 'Hub connectivity verified' 'Green'
        }
        catch {
            Write-DfLog 'Hub gateway unreachable — FA features may be limited.' 'Yellow'
        }
    }

    Write-DfLog 'Stopping any existing DemoForge stack...'
    Stop-CoreServices

    $dirs = @('demos', 'data', 'components')
    foreach ($d in $dirs) {
        $p = Join-Path $ProjectRoot $d
        if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
    }

    if ($env:DEMOFORGE_MODE -eq 'dev') {
        Write-DfLog 'Building dev images (frontend + backend)...'
        $ec = Invoke-Compose @('build', 'frontend', 'backend')
        if ($ec -ne 0) { exit $ec }
        & $docker @('image', 'prune', '-f', '--filter', 'until=1h') 2>$null | Out-Null
        Write-DfLog 'Starting services...'
        $ec = Invoke-Compose @('up', '-d', '--no-build')
        if ($ec -ne 0) { exit $ec }
    }
    else {
        Write-DfLog 'Starting services (pre-built images only)...'
        $ec = Invoke-Compose @('up', '-d', '--no-build')
        if ($ec -ne 0) {
            Write-Host "  Required images missing. Run: pwsh -File scripts/windows/hub-pull.ps1" -ForegroundColor Red
            exit 1
        }
    }

    $bePort = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { '9210' }
    $fePort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { '3000' }
    Write-Host ''
    $null = Wait-Http "http://127.0.0.1:${bePort}/docs" 'Backend API' 60
    $null = Wait-Http "http://127.0.0.1:${fePort}/" 'Frontend UI' 60

    Write-Host ''
    Write-DfLog '=========================================' 'Green'
    Write-DfLog ' DemoForge is running!' 'Green'
    Write-DfLog '=========================================' 'Green'
    Write-Host "  Frontend:  http://localhost:${fePort}"
    Write-Host "  Backend:   http://localhost:${bePort}"
    Write-Host "  API docs:  http://localhost:${bePort}/docs"
    Write-Host ''
    Write-Host '  Logs:   demoforge-windows.cmd logs' -ForegroundColor Yellow
    Write-Host '  Stop:   demoforge-windows.cmd stop' -ForegroundColor Yellow
    Write-Host ''
}

switch ($Command) {
    'start' { Start-DemoForgeCore }
    'stop' {
        Apply-DemoForgeEnvironment -ProjectRoot $ProjectRoot
        Stop-CoreServices
        Write-DfLog 'DemoForge stopped.' 'Green'
    }
    'restart' {
        Apply-DemoForgeEnvironment -ProjectRoot $ProjectRoot
        Stop-CoreServices
        Start-DemoForgeCore
    }
    'status' {
        Apply-DemoForgeEnvironment -ProjectRoot $ProjectRoot
        $name = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { 'demoforge' }
        Write-Host "=== DemoForge Status ($name) ===" -ForegroundColor Blue
        Write-Host ''
        Write-Host 'Services:' -ForegroundColor Cyan
        Push-Location $ProjectRoot
        try { & $docker @((Get-ComposeArgs $ProjectRoot) + @('ps')) }
        finally { Pop-Location }
        Write-Host ''
        Write-Host 'Demo containers (label=demoforge.demo):' -ForegroundColor Cyan
        & $docker @('ps', '--filter', 'label=demoforge.demo', '--format', 'table {{.Names}}\t{{.Status}}\t{{.Ports}}')
        Write-Host ''
        Write-Host 'Ports:' -ForegroundColor Cyan
        foreach ($port in @($env:BACKEND_PORT, $env:FRONTEND_PORT)) {
            if (-not $port) { continue }
            $inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($inUse) { Write-Host "  :$port -> in use" -ForegroundColor Green }
            else { Write-Host "  :$port -> free" -ForegroundColor Yellow }
        }
    }
    'logs' {
        Apply-DemoForgeEnvironment -ProjectRoot $ProjectRoot
        Push-Location $ProjectRoot
        try { & $docker @((Get-ComposeArgs $ProjectRoot) + @('logs', '-f', '--tail', '100')) }
        finally { Pop-Location }
    }
    'help' {
        Write-Host @'
Usage:
  demoforge-windows.cmd start | stop | restart | status | logs

Or:
  pwsh -File scripts/windows/demoforge.ps1 <command>

Optional: set DEMO_DOCKER_CLI=podman if you use Podman with the compose plugin.
'@
    }
}
