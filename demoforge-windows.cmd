@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PS51=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (set "DF_PS=pwsh") else (set "DF_PS=%PS51%")
if "%~1"=="" (
  "%DF_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\demoforge.ps1" help
  exit /b %ERRORLEVEL%
)
"%DF_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\demoforge.ps1" %*
exit /b %ERRORLEVEL%
