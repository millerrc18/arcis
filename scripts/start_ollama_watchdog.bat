@echo off
REM Convenience launcher for the Ollama watchdog.
REM
REM Starts the watchdog detached so it survives the launching shell.
REM Logs accumulate at logs/ollama-watchdog.log; tail to monitor.
REM
REM To stop: Get-Process powershell | ?{ $_.CommandLine -match 'ollama_watchdog' } | Stop-Process

cd /d "%~dp0\.."
start "" /MIN powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ollama_watchdog.ps1"
echo Ollama watchdog started (minimized window).
echo Logs: %CD%\logs\ollama-watchdog.log
