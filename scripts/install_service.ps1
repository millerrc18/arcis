<#
.SYNOPSIS
    Install, uninstall, restart, or inspect the Arcis watch loop as a
    Windows service via NSSM (Non-Sucking Service Manager).

.DESCRIPTION
    Wraps `nssm.exe` so the watch loop survives logoffs, reboots, and
    Python crashes with NSSM's built-in restart policy. All four
    commands must run from an elevated PowerShell session — creating,
    modifying, or starting a Windows service requires admin rights.

    The service runs `.venv\Scripts\python.exe -m src.main startup`
    with the repo root as working directory. Stdout and stderr are
    redirected to rotated log files under data\logs\.

.PARAMETER Command
    install   Create the service, configure restart policy + log
              redirection, and start it.
    uninstall Stop and remove the service. Leaves the log files in
              place so post-mortem analysis still has context.
    restart   Cleanly stop then start the service. Useful after
              deploying a code change.
    status    Show whether the service is running, its PID, and the
              NSSM-reported exit-code history if any.

.PARAMETER ServiceName
    Override the default service name (ArcisWatchLoop). Rarely needed
    except for side-by-side paper/live installs on one box.

.EXAMPLE
    PS> .\scripts\install_service.ps1 install
    PS> .\scripts\install_service.ps1 restart
    PS> .\scripts\install_service.ps1 status
    PS> .\scripts\install_service.ps1 uninstall

.NOTES
    Requires NSSM on PATH (https://nssm.cc/download). If NSSM is not
    installed, the script prints the install hint and exits 1.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('install', 'install-watchdog', 'uninstall', 'restart', 'status')]
    [string]$Command,

    [string]$ServiceName = 'ArcisWatchLoop'
)

$ErrorActionPreference = 'Stop'

# Resolve the repo root from this script's location — scripts/ sits at
# repo root, so ..\ from the script directory is the project root.
$RepoRoot        = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PythonExe       = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$LogDir          = Join-Path $RepoRoot 'data\logs'
$StdoutLog       = Join-Path $LogDir  'service.out.log'
$StderrLog       = Join-Path $LogDir  'service.err.log'
$WdStdoutLog     = Join-Path $LogDir  'ollama_watchdog.out.log'
$WdStderrLog     = Join-Path $LogDir  'ollama_watchdog.err.log'
$WatchdogService = 'ArcisOllamaWatchdog'

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "This command requires an elevated PowerShell session. Right-click PowerShell -> Run as Administrator."
        exit 1
    }
}

function Resolve-Nssm {
    $nssm = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if (-not $nssm) {
        Write-Error "NSSM not found on PATH. Install via 'choco install nssm' or download from https://nssm.cc/download"
        exit 1
    }
    return $nssm.Source
}

function Invoke-Install {
    Assert-Admin
    $nssm = Resolve-Nssm

    if (-not (Test-Path $PythonExe)) {
        Write-Error "Python not found at $PythonExe — create the venv first (python -m venv .venv)."
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    Write-Host "Installing service '$ServiceName' ..."
    & $nssm install $ServiceName $PythonExe '-m' 'src.main' 'startup'
    if ($LASTEXITCODE -ne 0) { Write-Error "nssm install failed ($LASTEXITCODE)"; exit $LASTEXITCODE }

    & $nssm set $ServiceName AppDirectory   $RepoRoot
    & $nssm set $ServiceName Description    'Arcis autonomous trading watch loop (scan + monitor + overnight jobs).'
    & $nssm set $ServiceName Start           SERVICE_AUTO_START
    & $nssm set $ServiceName AppStdout       $StdoutLog
    & $nssm set $ServiceName AppStderr       $StderrLog
    & $nssm set $ServiceName AppRotateFiles  1
    & $nssm set $ServiceName AppRotateOnline 1
    & $nssm set $ServiceName AppRotateBytes  10485760      # 10 MB per rotation
    # AppExit Default Restart is the NSSM default; repeat it here
    # explicitly so behavior doesn't depend on installer defaults.
    & $nssm set $ServiceName AppExit         Default Restart
    # Wait 10s after exit before relaunching so the watch loop's PID
    # lockfile atexit hook releases before the new process's startup
    # check fires (see CLAUDE.md "PID lockfile" section).
    & $nssm set $ServiceName AppRestartDelay 10000

    & $nssm start $ServiceName
    if ($LASTEXITCODE -ne 0) { Write-Error "nssm start failed ($LASTEXITCODE)"; exit $LASTEXITCODE }

    Write-Host "Installed. Logs: $StdoutLog" -ForegroundColor Green
}

function Invoke-Uninstall {
    Assert-Admin
    $nssm = Resolve-Nssm

    Write-Host "Stopping and removing '$ServiceName' ..."
    & $nssm stop   $ServiceName | Out-Null
    & $nssm remove $ServiceName confirm
    if ($LASTEXITCODE -ne 0) { Write-Error "nssm remove failed ($LASTEXITCODE)"; exit $LASTEXITCODE }

    Write-Host "Uninstalled (logs preserved at $LogDir)." -ForegroundColor Green
}

function Invoke-Restart {
    Assert-Admin
    $nssm = Resolve-Nssm

    Write-Host "Restarting '$ServiceName' ..."
    & $nssm restart $ServiceName
    if ($LASTEXITCODE -ne 0) { Write-Error "nssm restart failed ($LASTEXITCODE)"; exit $LASTEXITCODE }
    Write-Host "Restarted." -ForegroundColor Green
}

function Invoke-Status {
    $nssm = Resolve-Nssm
    $state = & $nssm status $ServiceName 2>&1
    Write-Host "Service : $ServiceName"
    Write-Host "State   : $state"

    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        $proc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
        if ($proc) { Write-Host "PID     : $($proc.ProcessId)" }
    }
    Write-Host "Logs    : $StdoutLog"
}

function Invoke-WatchdogInstall {
    Assert-Admin
    $nssm = Resolve-Nssm

    if (-not (Test-Path $PythonExe)) {
        Write-Error "Python not found at $PythonExe — create the venv first (python -m venv .venv)."
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    Write-Host "Installing service '$WatchdogService' ..."
    & $nssm install $WatchdogService $PythonExe '-m' 'src.scheduler.ollama_watchdog'
    if ($LASTEXITCODE -ne 0) { Write-Error "nssm install failed ($LASTEXITCODE)"; exit $LASTEXITCODE }

    & $nssm set $WatchdogService AppDirectory   $RepoRoot
    & $nssm set $WatchdogService Description    'Arcis Ollama lifecycle owner — GPU1-pinned inference server watchdog.'
    & $nssm set $WatchdogService Start           SERVICE_AUTO_START
    & $nssm set $WatchdogService AppStdout       $WdStdoutLog
    & $nssm set $WatchdogService AppStderr       $WdStderrLog
    & $nssm set $WatchdogService AppRotateFiles  1
    & $nssm set $WatchdogService AppRotateOnline 1
    & $nssm set $WatchdogService AppRotateBytes  10485760      # 10 MB per rotation

    # GPU1 pin + correct model-store path under LocalSystem.
    # CUDA_DEVICE_ORDER=PCI_BUS_ID makes index 1 deterministic regardless
    # of driver enumeration order.  OLLAMA_MODELS overrides the LocalSystem
    # default (~/.ollama resolves to the systemprofile, not the operator home).
    & $nssm set $WatchdogService AppEnvironmentExtra `
        "OLLAMA_MODELS=C:\Users\mille\.ollama\models" `
        "CUDA_VISIBLE_DEVICES=1" `
        "CUDA_DEVICE_ORDER=PCI_BUS_ID"

    # MAJOR-2 crash-escalation: explicit Restart policy + throttle window so
    # a recurring crash surfaces via NSSM's escalation rather than silently
    # exhausting the default throttle and going dark.  AppThrottle (ms) is the
    # minimum inter-restart interval; paired with T18's runtime monitor.
    & $nssm set $WatchdogService AppExit         Default Restart
    & $nssm set $WatchdogService AppThrottle     30000
    & $nssm set $WatchdogService AppRestartDelay 15000

    # No SCM service dependency — an SCM dependency wedge caused a 13-min
    # loop-down on 2026-05-22.  Start ordering is handled at install time only.

    & $nssm start $WatchdogService
    if ($LASTEXITCODE -ne 0) { Write-Error "nssm start failed ($LASTEXITCODE)"; exit $LASTEXITCODE }

    Write-Host "Installed. Logs: $WdStdoutLog" -ForegroundColor Green
}

switch ($Command) {
    'install'          { Invoke-Install; Invoke-WatchdogInstall }
    # v0.36.53: install ONLY the watchdog (for dual-GPU re-cutover scenarios
    # where ArcisWatchLoop already exists — `install` would collide on the
    # first nssm install and exit before reaching the watchdog).
    'install-watchdog' { Invoke-WatchdogInstall }
    'uninstall'        { Invoke-Uninstall }
    'restart'          { Invoke-Restart }
    'status'           { Invoke-Status }
}
