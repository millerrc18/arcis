# dump_watchloop.ps1 — collect a py-spy stack-dump from ArcisWatchLoop
#
# PID DISCOVERY RATIONALE:
#   NSSM-managed services run as LocalSystem and have no MainWindowTitle.
#   Instead, query NSSM for the actual child PID it tracks, which is more
#   reliable than matching by process name heuristics.  NSSM stores the
#   supervised PID in the registry under HKLM:\SYSTEM\CurrentControlSet\
#   Services\ArcisWatchLoop\Parameters\AppPID (written by nssm at start).
#   If that registry key is absent (NSSM not installed / service name
#   differs), fall back to WMI command-line matching on "arcis" or "watch".
#
# ELEVATION:
#   py-spy requires SeDebugPrivilege (admin).  We use Start-Process -Verb
#   RunAs so the UAC prompt appears even when the caller terminal is not
#   already elevated.

param(
    [int]$ProcessId = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- 1. Verify py-spy is installed ---
try {
    $null = & py-spy --version 2>&1
} catch {
    Write-Error "ERROR: py-spy not installed. Run: pip install py-spy"
    exit 1
}

# --- 2. Discover PID if not supplied ---
if ($ProcessId -eq 0) {
    # Try NSSM registry first
    $nssmKey = "HKLM:\SYSTEM\CurrentControlSet\Services\ArcisWatchLoop\Parameters"
    if (Test-Path $nssmKey) {
        $nssmPid = (Get-ItemProperty -Path $nssmKey -Name AppPID -ErrorAction SilentlyContinue).AppPID
        if ($nssmPid -and $nssmPid -gt 0) {
            $ProcessId = [int]$nssmPid
        }
    }

    # Fallback: scan python processes whose command line contains "arcis" or "watch"
    if ($ProcessId -eq 0) {
        $candidates = Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -match 'arcis|watch' }
        if ($candidates.Count -eq 1) {
            $ProcessId = [int]$candidates[0].ProcessId
        } elseif ($candidates.Count -gt 1) {
            Write-Error "ERROR: Multiple matching python processes found. Supply -ProcessId explicitly."
            exit 1
        }
    }

    if ($ProcessId -eq 0) {
        Write-Error "ERROR: Could not discover ArcisWatchLoop PID. Supply -ProcessId explicitly."
        exit 1
    }
}

# --- 3. Build output path ---
$timestamp = (Get-Date -Format "yyyyMMddTHHmmss")
$outDir = "C:/arcis/halcyon-lab/logs"
$outFile = "$outDir/py-spy-watchloop-$timestamp.txt"

if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}

# --- 4. Elevate and invoke py-spy dump ---
# py-spy dump writes to stdout; we capture it via -RedirectStandardOutput.
# Start-Process -Verb RunAs spawns an elevated child; -Wait blocks until done.
$tmpOut = [System.IO.Path]::GetTempFileName()
$tmpErr = [System.IO.Path]::GetTempFileName()

try {
    $proc = Start-Process `
        -FilePath "py-spy" `
        -ArgumentList @("dump", "--pid", "$ProcessId") `
        -Verb RunAs `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $tmpOut `
        -RedirectStandardError  $tmpErr

    $dumpContent = Get-Content $tmpOut -Raw -ErrorAction SilentlyContinue
    $errContent  = Get-Content $tmpErr -Raw -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        if ($errContent) { Write-Error "py-spy error: $errContent" }
        exit $proc.ExitCode
    }

    Set-Content -Path $outFile -Value $dumpContent -Encoding UTF8
    Write-Output $outFile
    exit 0
} finally {
    Remove-Item $tmpOut -ErrorAction SilentlyContinue
    Remove-Item $tmpErr -ErrorAction SilentlyContinue
}
