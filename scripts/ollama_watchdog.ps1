# Ollama watchdog — monitors /api/tags, restarts on death, captures stderr.
#
# Usage:
#   powershell -File scripts/ollama_watchdog.ps1
#   (or via scripts/start_ollama_watchdog.bat for convenience)
#
# Design notes:
# - Polls /api/tags every 30s. On failure, kills any orphan ollama* processes
#   and starts a fresh `ollama serve` with stderr/stdout captured to logs/.
#   This closes the gap noted in the 2026-05-06 corpus crash investigation,
#   where -WindowStyle Hidden discarded the runner crash signature entirely.
# - Circuit breaker: 3 restarts in any 10-minute rolling window pauses the
#   watchdog for 5 minutes. Prevents tight crash loops from masking a real
#   underlying issue (driver bug, persistent OOM, hardware fault).
# - All events go to logs/ollama-watchdog.log so post-mortem is possible.

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$watchdogLog = Join-Path $repoRoot "logs/ollama-watchdog.log"
$ollamaErrLog = Join-Path $repoRoot "logs/ollama-daemon.err"
$ollamaOutLog = Join-Path $repoRoot "logs/ollama-daemon.out"
$ollamaExe = "C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe"
$apiUrl = "http://127.0.0.1:11434/api/tags"
$pollIntervalSec = 30
$maxRestartsPer10Min = 3
$pauseAfterCircuitBreakSec = 300
$startupGraceSec = 8

function Log {
    param([string]$msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Add-Content -Path $watchdogLog -Value $line
    Write-Host $line
}

function Test-OllamaHealthy {
    try {
        $r = Invoke-WebRequest -Uri $apiUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Stop-OllamaProcesses {
    Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

function Start-OllamaHeadless {
    if (-not (Test-Path $ollamaExe)) {
        Log "ERROR: ollama exe not found at $ollamaExe"
        return $false
    }
    # CRITICAL: -RedirectStandardError captures runner crash output that
    # -WindowStyle Hidden alone discards. Append mode preserves history.
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" `
        -WindowStyle Hidden `
        -RedirectStandardError $ollamaErrLog `
        -RedirectStandardOutput $ollamaOutLog
    return $true
}

# Restart history for circuit breaker (rolling 10-min window)
$restartHistory = @()

Log "Watchdog starting. Poll=$pollIntervalSec s; max_restarts_per_10min=$maxRestartsPer10Min; circuit_pause=$pauseAfterCircuitBreakSec s"
Log "Logs: watchdog=$watchdogLog | daemon_err=$ollamaErrLog | daemon_out=$ollamaOutLog"

# Initial health check
if (Test-OllamaHealthy) {
    Log "Initial health check OK"
} else {
    Log "Initial health check FAILED — starting Ollama"
    Stop-OllamaProcesses
    Start-OllamaHeadless | Out-Null
    Start-Sleep -Seconds $startupGraceSec
    if (Test-OllamaHealthy) {
        Log "Initial start succeeded"
    } else {
        Log "WARNING: Initial start did not yield a healthy daemon. Will keep trying via main loop."
    }
}

while ($true) {
    Start-Sleep -Seconds $pollIntervalSec

    if (Test-OllamaHealthy) { continue }

    Log "Ollama unreachable — restart sequence initiating"

    # Circuit breaker
    $now = Get-Date
    $restartHistory = @($restartHistory | Where-Object { ($now - $_).TotalMinutes -lt 10 })
    if ($restartHistory.Count -ge $maxRestartsPer10Min) {
        Log "CIRCUIT BREAKER: $($restartHistory.Count) restarts in last 10 min. Pausing $pauseAfterCircuitBreakSec s."
        if (Test-Path $ollamaErrLog) {
            Log "Last 10 lines of daemon err log:"
            Get-Content $ollamaErrLog -Tail 10 | ForEach-Object { Log "  STDERR: $_" }
        }
        Start-Sleep -Seconds $pauseAfterCircuitBreakSec
        $restartHistory = @()
        continue
    }

    Stop-OllamaProcesses
    if (-not (Start-OllamaHeadless)) {
        Log "Restart attempt FAILED at Start-Process step"
        continue
    }
    $restartHistory += $now
    Start-Sleep -Seconds $startupGraceSec

    if (Test-OllamaHealthy) {
        Log "Restart $($restartHistory.Count): SUCCESS"
    } else {
        Log "Restart $($restartHistory.Count): FAILED — daemon not responding after ${startupGraceSec}s grace"
        if (Test-Path $ollamaErrLog) {
            Log "Last 5 lines of daemon err log:"
            Get-Content $ollamaErrLog -Tail 5 | ForEach-Object { Log "  STDERR: $_" }
        }
    }
}
