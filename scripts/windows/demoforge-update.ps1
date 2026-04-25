#Requires -Version 5.1
<#
.SYNOPSIS
  Windows equivalent of scripts/demoforge-update.sh: git pull, re-run self if HEAD moved, then fa-update.ps1.

.EXAMPLE
  pwsh -File scripts/windows/demoforge-update.ps1
#>
$ErrorActionPreference = 'Stop'
$PSScriptRoot = if ($MyInvocation.MyCommand.Path) { (Split-Path -Parent $MyInvocation.MyCommand.Path) } elseif ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
. (Join-Path $PSScriptRoot 'DemoForge-Env.ps1')

$ProjectRoot = Get-DemoForgeProjectRoot
$maxSelfDepth = 8
$depth = 0
if ($env:DEMOFORGE_UPDATE_SELF_DEPTH -match '^\d+$') {
    $depth = [int]$env:DEMOFORGE_UPDATE_SELF_DEPTH
}
if ($depth -gt $maxSelfDepth) {
    Write-Host "demoforge-update.ps1: re-exec depth exceeded ($maxSelfDepth). Resolve git state manually." -ForegroundColor Red
    exit 1
}

Write-Host 'DemoForge - pulling latest repo (Windows)' -ForegroundColor Green
Write-Host ''

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'git not on PATH; skipping git pull. Install Git for Windows or run from a clone with git available.' -ForegroundColor Yellow
}
else {
    Push-Location $ProjectRoot
    try {
        $before = (& git rev-parse HEAD 2>$null | Out-String).Trim()
        $savedEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & git pull 2>&1 | Out-Host
        }
        finally {
            $ErrorActionPreference = $savedEap
        }
        $after = (& git rev-parse HEAD 2>$null | Out-String).Trim()

        if ($before -and $after -and $before -ne $after) {
            Write-Host 'Scripts updated - re-running demoforge-update.ps1 with latest copy...' -ForegroundColor Green
            Write-Host ''
            $exe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
            if (-not $exe) { $exe = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source }
            if (-not $exe) {
                Write-Error 'Neither pwsh nor powershell.exe found on PATH.'
                exit 1
            }
            $thisScript = $MyInvocation.MyCommand.Path
            $env:DEMOFORGE_UPDATE_SELF_DEPTH = [string]($depth + 1)
            $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $thisScript)
            $p = Start-Process -FilePath $exe -ArgumentList $argv -Wait -PassThru -NoNewWindow
            $childExit = [int]$p.ExitCode
            Remove-Item Env:DEMOFORGE_UPDATE_SELF_DEPTH -ErrorAction SilentlyContinue
            exit $childExit
        }
    }
    finally {
        Pop-Location
    }
}

$faUpdate = Join-Path $PSScriptRoot 'fa-update.ps1'
$rc = Invoke-DfScriptFile -Path $faUpdate
Remove-Item Env:DEMOFORGE_UPDATE_SELF_DEPTH -ErrorAction SilentlyContinue
exit $rc
