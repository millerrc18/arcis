# capture_pg_activity.ps1 — Capture pg_stat_activity snapshots every 30s for cutover forensics.
# Usage: .\scripts\capture_pg_activity.ps1
# Stop: Ctrl+C
# Output: C:/arcis/logs/pg-activity-<timestamp>.log

$logPath = "C:/arcis/logs/pg-activity-$(Get-Date -Format 'yyyy-MM-dd-HHmmss').log"
Write-Host "Capturing pg_stat_activity every 30s to $logPath"
Write-Host "Press Ctrl+C to stop."

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
    "=== $ts ===" | Out-File -Append $logPath
    docker exec halcyon-pg psql -U halcyon -d halcyon -c `
        "SELECT pid, usename, client_addr, application_name, state, query_start, LEFT(query, 200) AS query_preview FROM pg_stat_activity WHERE datname='halcyon' ORDER BY query_start DESC;" `
        | Out-File -Append $logPath
    Start-Sleep -Seconds 30
}
