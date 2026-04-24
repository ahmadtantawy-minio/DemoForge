# Shared helpers for Windows-native DemoForge scripts (FA-oriented).
# Dot-source from fa-setup.ps1 / demoforge.ps1:  . "$PSScriptRoot/DemoForge-Env.ps1"

function Get-DemoForgeProjectRoot {
    (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Get-DockerExecutable {
    if ($env:DEMO_DOCKER_CLI) { return $env:DEMO_DOCKER_CLI.Trim() }
    return 'docker'
}

function Test-DockerAvailable {
    $docker = Get-DockerExecutable
    if (-not (Get-Command $docker -ErrorAction SilentlyContinue)) {
        Write-Error "$docker not found. Install Docker Desktop or Podman, or set DEMO_DOCKER_CLI to your engine CLI."
        return $false
    }
    $composeTest = & $docker @('compose', 'version') 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker Compose v2 required ('$docker compose version' failed). Install the Compose plugin."
        return $false
    }
    $info = & $docker @('info') 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Container engine is not running. Start Docker Desktop / Podman machine."
        return $false
    }
    return $true
}

function Import-DotEnvFile {
    param(
        [string]$Path,
        [hashtable]$Into
    )
    if (-not (Test-Path $Path)) { return }
    Get-Content -Path $Path -Encoding utf8 | ForEach-Object {
        $line = $_.TrimEnd()
        if ($line -match '^\s*#' -or $line -eq '') { return }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { return }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim()
        if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length - 2) }
        elseif ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length - 2) }
        $Into[$k] = $v
    }
}

function Apply-DemoForgeEnvironment {
    param(
        [string]$ProjectRoot,
        [string]$CallerMode = ''
    )
    $vars = @{}
    Import-DotEnvFile (Join-Path $ProjectRoot '.env.hub') $vars
    Import-DotEnvFile (Join-Path $ProjectRoot '.env.local') $vars

    foreach ($kv in $vars.GetEnumerator()) {
        Set-Item -Path "env:$($kv.Key)" -Value $kv.Value
    }

    if ($CallerMode) {
        Set-Item -Path 'env:DEMOFORGE_MODE' -Value $CallerMode
    }
    elseif (
        ($env:DEMOFORGE_MODE -eq 'standard' -or -not $env:DEMOFORGE_MODE) -and
        $env:DEMOFORGE_FA_ID
    ) {
        Set-Item -Path 'env:DEMOFORGE_MODE' -Value 'fa'
        Set-EnvLocalKey -ProjectRoot $ProjectRoot -Key 'DEMOFORGE_MODE' -Value 'fa'
    }

    $gitDesc = ''
    try {
        $gitDesc = (& git -C $ProjectRoot 'describe' '--tags' '--always' 2>$null | Out-String).Trim()
    } catch { }
    if (-not $gitDesc) { $gitDesc = 'dev' }
    Set-Item -Path 'env:DEMOFORGE_VERSION' -Value $(if ($env:DEMOFORGE_VERSION) { $env:DEMOFORGE_VERSION } else { $gitDesc })

    if ($env:DEMOFORGE_HUB_LOCAL -ne '1' -and (Test-Path (Join-Path $ProjectRoot '.env.hub'))) {
        $hubLines = @{}
        Import-DotEnvFile (Join-Path $ProjectRoot '.env.hub') $hubLines
        if ($hubLines['DEMOFORGE_HUB_API_ADMIN_KEY']) {
            Set-Item -Path 'env:DEMOFORGE_HUB_API_ADMIN_KEY' -Value $hubLines['DEMOFORGE_HUB_API_ADMIN_KEY']
        }
        $gw = $hubLines['DEMOFORGE_GATEWAY_API_KEY']
        if (-not $gw) { $gw = $hubLines['DEMOFORGE_API_KEY'] }
        if ($gw) { Set-Item -Path 'env:DEMOFORGE_GATEWAY_API_KEY' -Value $gw }
    }

    if ($env:DEMOFORGE_MODE -eq 'dev') {
        Set-Item -Path 'env:BACKEND_PORT' -Value '9211'
        Set-Item -Path 'env:FRONTEND_PORT' -Value '3001'
        Set-Item -Path 'env:COMPOSE_PROJECT_NAME' -Value 'demoforge-dev'
    }
    else {
        Set-Item -Path 'env:BACKEND_PORT' -Value '9210'
        Set-Item -Path 'env:FRONTEND_PORT' -Value '3000'
        Set-Item -Path 'env:COMPOSE_PROJECT_NAME' -Value 'demoforge'
    }
}

function Set-EnvLocalKey {
    param(
        [string]$ProjectRoot,
        [string]$Key,
        [string]$Value
    )
    $path = Join-Path $ProjectRoot '.env.local'
    $lines = @()
    if (Test-Path $path) {
        $found = $false
        foreach ($line in Get-Content -Path $path -Encoding utf8) {
            if ($line -match '^\s*#' -or ($line.Trim() -eq '')) {
                $lines += $line
                continue
            }
            if ($line -match "^$([regex]::Escape($Key))=") {
                $lines += "${Key}=$Value"
                $found = $true
            }
            else {
                $lines += $line
            }
        }
        if (-not $found) { $lines += "${Key}=$Value" }
    }
    else {
        $lines += "${Key}=$Value"
    }
    $lines | Set-Content -Path $path -Encoding utf8
}

function Get-ComposeArgs {
    param([string]$ProjectRoot)
    $composeArgs = @('compose', '-f', (Join-Path $ProjectRoot 'docker-compose.yml'))
    if ($env:DEMOFORGE_MODE -eq 'dev' -and (Test-Path (Join-Path $ProjectRoot 'docker-compose.dev.yml'))) {
        $composeArgs += '-f'
        $composeArgs += (Join-Path $ProjectRoot 'docker-compose.dev.yml')
    }
    if ($env:DEMOFORGE_HUB_LOCAL -eq '1') {
        $composeArgs += '--profile'
        $composeArgs += 'local-hub'
    }
    return ,$composeArgs
}
