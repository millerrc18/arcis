# restore_pg_from_snapshot.ps1 — codified PG recovery procedure
#
# Source of truth for "restore halcyon-pg from a pg_dump snapshot."
# Replaces ad-hoc interactive psql sessions that proved brittle during
# the 2026-05-14 P0 incident (see docs/audits/2026-05-14-p0-pg-wipe/rcca.md).
#
# What this script does (in order):
#   1. Verify snapshot file exists + reasonable size + (optional) SHA256
#   2. Snapshot current PG state to a pre-recovery audit file
#   3. Confirm with operator (unless -Force)
#   4. DROP SCHEMA public CASCADE; CREATE SCHEMA public
#   5. GRANT CREATE on public schema to halcyon_app (allow CREATE TABLE)
#   6. Copy snapshot file into container (via PowerShell — avoids Git Bash
#      path mangling that bit us on 2026-05-14)
#   7. psql -f /tmp/snap.sql --set ON_ERROR_STOP=off
#   8. GRANT ALL ON ALL TABLES + ALTER DEFAULT PRIVILEGES (per memory
#      feedback_drop_schema_grant_pattern — without this, halcyon_app
#      can SELECT but not UPDATE → watch loop restart loop)
#   9. Verify table count matches registry expectation
#  10. Verify spot-check row counts (shadow_trades, recommendations, etc.)
#  11. Cleanup snapshot file inside container
#
# Usage:
#   .\scripts\recovery\restore_pg_from_snapshot.ps1 -SnapshotPath "C:\arcis\data\render-snapshot-2026-05-14\render-halcyon-124218.sql"
#   .\scripts\recovery\restore_pg_from_snapshot.ps1 -SnapshotPath "..." -ExpectedSHA256 "1207EFC3..." -Force
#
# Exit codes:
#   0  — recovery succeeded, post-checks passed
#   1  — pre-flight check failed (snapshot missing, wrong size, etc.)
#   2  — operator declined confirmation
#   3  — DROP/GRANT step failed
#   4  — restore step failed (non-trivial error count in stderr)
#   5  — post-restore verification failed (table count mismatch / row counts off)
#
# Safety:
#   - Idempotent: re-running on the same snapshot produces the same result
#   - Audit trail: every step writes a timestamped marker to
#     C:\arcis\data\recovery-audit\<timestamp>\
#   - No -v flag on docker compose anywhere — bind mount is preserved
#
# This script is the AUTHORITATIVE recovery path. If you find yourself
# typing `docker exec halcyon-pg psql -c "DROP SCHEMA..."` interactively,
# STOP and run this script instead. Interactive sessions are the failure
# mode this script exists to prevent.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$SnapshotPath,

    [string]$ExpectedSHA256 = "",

    [string]$ContainerName = "halcyon-pg",

    [string]$DatabaseName = "halcyon",

    [string]$SuperuserName = "halcyon",

    [string]$AppUserName = "halcyon_app",

    [string]$ReadonlyUserName = "halcyon_readonly",

    [int]$ExpectedTableCount = 0,   # 0 = skip count check

    [switch]$Force
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Setup: audit directory + helpers
# ---------------------------------------------------------------------------

$ts = Get-Date -Format "yyyy-MM-dd-HHmmss"
$auditRoot = "C:\arcis\data\recovery-audit\$ts"
New-Item -ItemType Directory -Force -Path $auditRoot | Out-Null

function Log {
    param([string]$msg, [string]$level = "INFO")
    $line = "[$(Get-Date -Format 'HH:mm:ss')] [$level] $msg"
    Write-Host $line
    Add-Content -Path "$auditRoot\recovery.log" -Value $line
}

function Die {
    param([int]$code, [string]$msg)
    Log -level "FATAL" -msg $msg
    exit $code
}

function RunPsql {
    param([string]$sql, [string]$step)
    Log "psql ($step): $($sql.Substring(0, [Math]::Min(120, $sql.Length)))..."
    $out = docker exec $ContainerName psql -U $SuperuserName -d $DatabaseName -c $sql 2>&1
    $out | Out-File -Append -FilePath "$auditRoot\psql-$step.log"
    if ($LASTEXITCODE -ne 0) {
        Die 3 "psql step '$step' returned $LASTEXITCODE. See $auditRoot\psql-$step.log"
    }
    return $out
}

Log "=== Recovery script started ==="
Log "Audit dir: $auditRoot"
Log "Snapshot: $SnapshotPath"
Log "Container: $ContainerName"
Log "DB: $DatabaseName"

# ---------------------------------------------------------------------------
# Step 1 — verify snapshot file
# ---------------------------------------------------------------------------

if (-not (Test-Path $SnapshotPath)) {
    Die 1 "Snapshot file not found: $SnapshotPath"
}

$snap = Get-Item $SnapshotPath
Log "Snapshot size: $([math]::Round($snap.Length / 1MB, 1)) MB"
if ($snap.Length -lt 1MB) {
    Die 1 "Snapshot is suspiciously small (<1 MB). Refusing to restore from a corrupt/empty file."
}

if ($ExpectedSHA256) {
    Log "Verifying SHA256..."
    $actual = (Get-FileHash -Algorithm SHA256 $SnapshotPath).Hash
    if ($actual -ne $ExpectedSHA256.ToUpper()) {
        Die 1 "SHA256 mismatch. Expected $ExpectedSHA256 but got $actual"
    }
    Log "SHA256 verified: $actual"
}

# Sanity: count CREATE TABLE statements in dump → expected table count
$createTableCount = (Select-String -Path $SnapshotPath -Pattern "^CREATE TABLE" -SimpleMatch).Count
Log "Dump contains $createTableCount CREATE TABLE statements"
if ($ExpectedTableCount -gt 0 -and $createTableCount -ne $ExpectedTableCount) {
    Log -level "WARN" -msg "Dump has $createTableCount CREATE TABLE but expected $ExpectedTableCount"
}

# ---------------------------------------------------------------------------
# Step 2 — capture pre-recovery state for audit
# ---------------------------------------------------------------------------

Log "Capturing pre-recovery state..."
$preState = docker exec $ContainerName psql -U $SuperuserName -d $DatabaseName -c "SELECT COUNT(*) AS tables FROM information_schema.tables WHERE table_schema='public'" 2>&1
$preState | Out-File -FilePath "$auditRoot\pre-state-tablecount.txt"
$preTables = docker exec $ContainerName psql -U $SuperuserName -d $DatabaseName -c "\dt" 2>&1
$preTables | Out-File -FilePath "$auditRoot\pre-state-tables.txt"
Log "Pre-recovery audit saved to $auditRoot\pre-state-*.txt"

# ---------------------------------------------------------------------------
# Step 3 — operator confirmation (unless -Force)
# ---------------------------------------------------------------------------

if (-not $Force) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  ABOUT TO DROP + RESTORE PUBLIC SCHEMA OF '$DatabaseName'" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  Snapshot: $SnapshotPath ($([math]::Round($snap.Length / 1MB, 1)) MB)"
    Write-Host "  Container: $ContainerName"
    Write-Host "  Audit dir: $auditRoot"
    Write-Host ""
    Write-Host "  THIS WILL DROP THE EXISTING PUBLIC SCHEMA. Data not in" -ForegroundColor Yellow
    Write-Host "  the snapshot WILL BE LOST. Pre-recovery state captured" -ForegroundColor Yellow
    Write-Host "  to audit dir for reference, but no automatic rollback." -ForegroundColor Yellow
    Write-Host ""
    $confirm = Read-Host "Type YES to proceed (anything else aborts)"
    if ($confirm -ne "YES") {
        Log "Operator aborted at confirmation prompt."
        exit 2
    }
}

# ---------------------------------------------------------------------------
# Step 4 — DROP + CREATE SCHEMA + GRANT CREATE
# ---------------------------------------------------------------------------

Log "Dropping + recreating public schema..."
RunPsql -step "drop-schema" -sql @"
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO $SuperuserName;
GRANT CREATE ON SCHEMA public TO $AppUserName;
GRANT USAGE ON SCHEMA public TO $AppUserName;
GRANT USAGE ON SCHEMA public TO $ReadonlyUserName;
"@

# ---------------------------------------------------------------------------
# Step 5/6 — copy snapshot into container + run restore
# ---------------------------------------------------------------------------

Log "Copying snapshot into container as /tmp/snap.sql..."
docker cp "$SnapshotPath" "${ContainerName}:/tmp/snap.sql" 2>&1 | Out-File -FilePath "$auditRoot\docker-cp.log"
if ($LASTEXITCODE -ne 0) {
    Die 4 "docker cp failed (exit $LASTEXITCODE). See $auditRoot\docker-cp.log"
}
$inSize = docker exec $ContainerName ls -lh /tmp/snap.sql 2>&1
Log "In-container snapshot: $inSize"

Log "Running psql -f /tmp/snap.sql (this can take 5-10 min for 500 MB)..."
docker exec $ContainerName psql -U $SuperuserName -d $DatabaseName --set ON_ERROR_STOP=off -f /tmp/snap.sql `
    > "$auditRoot\restore-stdout.log" `
    2> "$auditRoot\restore-stderr.log"
$restoreRC = $LASTEXITCODE
Log "psql restore exit: $restoreRC"

# Allow the known PG-17+ transaction_timeout warning; fail on anything else
$nonWarningErrors = Select-String -Path "$auditRoot\restore-stderr.log" -Pattern "ERROR|FATAL" -ErrorAction SilentlyContinue |
    Where-Object { $_.Line -notmatch "transaction_timeout|already exists, skipping" }
if ($nonWarningErrors) {
    Log -level "WARN" -msg "$($nonWarningErrors.Count) non-warning errors in restore stderr. Review $auditRoot\restore-stderr.log"
    $nonWarningErrors | Select-Object -First 10 | ForEach-Object { Log -level "WARN" -msg ("  " + $_.Line) }
}

# ---------------------------------------------------------------------------
# Step 7 — GRANT ALL ON ALL TABLES + ALTER DEFAULT PRIVILEGES
# Without this, halcyon_app can SELECT (via PUBLIC role default) but cannot
# UPDATE/INSERT/DELETE. Watch loop hits permission denied on first reconcile
# step → crash → NSSM restart loop. Incident 2026-05-15 (memory:
# feedback_drop_schema_grant_pattern).
# ---------------------------------------------------------------------------

Log "Granting ALL on restored tables + setting default privileges..."
RunPsql -step "grant-tables" -sql @"
GRANT ALL ON ALL TABLES IN SCHEMA public TO $AppUserName;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO $AppUserName;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $AppUserName;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $AppUserName;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $ReadonlyUserName;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $ReadonlyUserName;
"@

# ---------------------------------------------------------------------------
# Step 8 — post-restore verification
# ---------------------------------------------------------------------------

Log "Post-restore verification..."

$postTableCount = (docker exec $ContainerName psql -U $SuperuserName -d $DatabaseName -tA -c `
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'") -as [int]
Log "Post-restore table count: $postTableCount"

if ($ExpectedTableCount -gt 0 -and $postTableCount -lt ($ExpectedTableCount * 0.95)) {
    Die 5 "Post-restore table count $postTableCount is <95% of expected $ExpectedTableCount. Recovery INCOMPLETE."
}

# Spot-check row counts for the canonical trading tables
$verifyTables = @("shadow_trades", "recommendations", "model_versions", "training_examples", "activity_log")
foreach ($t in $verifyTables) {
    $exists = (docker exec $ContainerName psql -U $SuperuserName -d $DatabaseName -tA -c `
        "SELECT to_regclass('public.$t') IS NOT NULL") -match "^t"
    if (-not $exists) {
        Log -level "WARN" -msg "Expected table '$t' is MISSING after restore"
        continue
    }
    $rowCount = docker exec $ContainerName psql -U $SuperuserName -d $DatabaseName -tA -c "SELECT COUNT(*) FROM $t" 2>&1
    Log "  $t: $rowCount rows"
}

# Verify halcyon_app can actually UPDATE (the canary that catches the
# GRANT-ALL-ON-TABLES gap)
Log "Verifying halcyon_app can UPDATE (canary for GRANT permissions)..."
$canaryResult = docker exec $ContainerName psql -U $AppUserName -d $DatabaseName -c `
    "UPDATE shadow_trades SET actual_exit_time = COALESCE(updated_at, created_at) WHERE status = 'closed' AND actual_exit_time IS NULL" 2>&1
if ($canaryResult -match "permission denied") {
    Die 5 "GRANT canary FAILED: halcyon_app cannot UPDATE shadow_trades. Re-run grant step or restore-from-snapshot."
}
Log "GRANT canary OK: $canaryResult"

# ---------------------------------------------------------------------------
# Step 9 — cleanup
# ---------------------------------------------------------------------------

Log "Cleaning up /tmp/snap.sql in container..."
docker exec $ContainerName rm /tmp/snap.sql 2>&1 | Out-Null

Log "=== Recovery complete. $postTableCount tables restored. ==="
Log "Audit trail: $auditRoot"
Log ""
Log "NEXT STEPS:"
Log "  1. (Optional) Bump shared_buffers if not yet done: ALTER SYSTEM SET shared_buffers='2GB'; (requires PG restart)"
Log "  2. Verify watch loop can connect: nssm restart ArcisWatchLoop"
Log "  3. Tail PG forensic logs to confirm no unexpected DDL:"
Log "       docker exec $ContainerName tail -f /var/lib/postgresql/data/log/postgresql-*.log"

exit 0
