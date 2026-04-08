# Sprint: Dashboard Data Integrity Hotfix

> **Branch:** `fix/dashboard-data-integrity`
> **Priority:** CRITICAL — 8 of 21 dashboard pages show broken/missing data
> **Estimated time:** 4-6 hours CC time
> **Tag on completion:** v0.16.0

> ⚠️ **Read first:** `MASTER.md`, then this entire sprint before starting.
> This sprint fixes 5 root causes affecting dashboard data integrity.
> Ralph looped 3×. Every task has exact file paths and line references.

---

## Pre-Flight

```bash
git checkout main
git pull origin main
git checkout -b fix/dashboard-data-integrity
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py
# Record baseline test count
cd frontend && npm run build && cd ..
# Verify no file > 400 lines is being created (all edits are to existing files)
```

---

## Root Cause A: CTO Report Computation Bugs (3 tasks)

### Task 1: Fix targets_hit_pct filter — wrong exit_reason values

**Problem:** `targets_hit_pct` shows 0.0% despite 13 trades hitting target_1. The
filter checks for `"target_1"` and `"target_2"` but the executor writes
`"target_1_hit"` and `"target_2_hit"`.

**File:** `src/api/cloud_routes/analytics.py`

**Find this line (~511):**
```python
targets_hit = [t for t in closed_recent if t.get("exit_reason") in ("target_1", "target_2")]
```

**Replace with:**
```python
targets_hit = [t for t in closed_recent if t.get("exit_reason") in ("target_1_hit", "target_2_hit", "target_1", "target_2")]
```

Note: Include both variants for backward compatibility — older trades may use the short form.

**Test:** `test_targets_hit_pct_filter` — Create mock trades with exit_reason
`"target_1_hit"`, verify targets_hit_pct > 0.

---

### Task 2: Add 7 missing fund metrics to CTO report

**Problem:** Frontend (CTOReport.jsx lines 345-350) expects 7 fields the backend
never computes: `monthly_batting_avg`, `return_skewness`, `best_trade_pct`,
`worst_trade_pct`, `total_return_pct`, `avg_hold_period_days` (in fund_metrics),
and `avg_mfe_winners` (in execution_analysis).

**File:** `src/api/cloud_routes/analytics.py`

**In the cto_report function, after the existing fund_metrics computation
(~line 540, after the calmar_ratio calculation), add these fields:**

```python
# --- Additional fund metrics (dashboard expects these) ---
if pnls:
    fund_metrics["best_trade_pct"] = round(max(pnls), 2)
    fund_metrics["worst_trade_pct"] = round(min(pnls), 2)
    fund_metrics["total_return_pct"] = round(sum(pnls), 2)

    # Return skewness
    if len(pnls) >= 3:
        n = len(pnls)
        mean_p = sum(pnls) / n
        std_p = (sum((p - mean_p) ** 2 for p in pnls) / (n - 1)) ** 0.5
        if std_p > 0:
            skew = (n / ((n - 1) * (n - 2))) * sum(((p - mean_p) / std_p) ** 3 for p in pnls)
            fund_metrics["return_skewness"] = round(skew, 3)

    # Monthly batting avg: % of calendar months with positive total P&L
    monthly_pnl = {}
    for trade in closed_recent:
        exit_time = trade.get("actual_exit_time") or trade.get("updated_at") or ""
        month_key = exit_time[:7]  # "2026-03"
        if month_key:
            monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + (trade.get("pnl_dollars", 0) or 0)
    if monthly_pnl:
        winning_months = sum(1 for v in monthly_pnl.values() if v > 0)
        fund_metrics["monthly_batting_avg"] = round(winning_months / len(monthly_pnl) * 100, 1)

    # Avg hold period (duplicate in fund_metrics for the second card row)
    if durations:
        fund_metrics["avg_hold_period_days"] = round(sum(durations) / len(durations), 1)
```

**In the execution_analysis dict (~line 512), add avg_mfe_winners:**

```python
execution_analysis = {
    "avg_hold_period_days": round(sum(durations) / len(durations), 1) if durations else 0,
    "targets_hit_pct": round(len(targets_hit) / len(closed_recent) * 100, 1) if closed_recent else 0,
    "timeout_pct": round(len(timeouts) / len(closed_recent) * 100, 1) if closed_recent else 0,
    "avg_mfe_winners": None,  # MFE requires intraday data not yet tracked
}
```

**Test:** `test_cto_fund_metrics_complete` — Verify all 7 fields are present and
non-null when trades exist.

---

### Task 3: Write market_regime to recommendations table

**Problem:** `market_regime` column exists in recommendations but is never
populated. All 52 trades show regime = "unknown" on the CTO Report.

**File:** `src/journal/store.py`

**Find the `row = {` dict in `log_recommendation()` (~line 71). Add this field
to the dict (e.g., after the `"enriched_prompt"` line):**

```python
"market_regime": features.get("market_regime"),
```

**Then verify the feature is available.** Check `src/features/engine.py` — the
`compute_all_features()` function should include market_regime in its output.

**File:** `src/features/engine.py`

Search for where regime is computed. If `market_regime` is not in the returned
features dict, add it:

```python
# After compute_market_regime() is called:
features[ticker]["market_regime"] = regime
```

**Test:** `test_recommendation_has_market_regime` — Create a recommendation via
`log_recommendation()`, verify `market_regime` is not NULL.

---

## Root Cause B: Command Queue Not Syncing (1 task)

### Task 4: Enable pending_commands sync (cloud → local)

**Problem:** Dashboard "Run Simulation" and "Run Stress Test" buttons write to
Postgres `pending_commands`, but the local machine never reads them because the
table has `sync_to_postgres=False`. Commands stay PENDING forever.

**File:** `src/schema/registry.py`

**Find the `pending_commands` table definition and change:**
```python
sync_to_postgres=False,
```
**To:**
```python
sync_to_postgres=True,
sync_mode="incremental",
sync_time_column="created_at",
```

**File:** `src/sync/render_sync.py`

The standard sync pushes local → Postgres. For pending_commands, we need
Postgres → local (reverse direction). Add a dedicated pull function:

```python
def pull_pending_commands(pg_conn, local_conn, logger) -> int:
    """Pull pending commands from Postgres to local SQLite.

    This is the reverse of the normal sync direction: cloud dashboard
    writes commands to Postgres, local machine pulls and executes them.
    Only pulls commands with status='pending' to avoid re-processing.
    """
    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pending_commands WHERE status = 'pending'"
            )
            rows = cur.fetchall()
            if not rows:
                return 0
            cols = [desc[0] for desc in cur.description]
            count = 0
            for row in rows:
                row_dict = dict(zip(cols, row))
                cmd_id = row_dict["command_id"]
                # Check if already exists locally
                existing = local_conn.execute(
                    "SELECT command_id FROM pending_commands WHERE command_id = ?",
                    (cmd_id,)
                ).fetchone()
                if existing:
                    continue
                placeholders = ", ".join("?" for _ in cols)
                col_str = ", ".join(cols)
                local_conn.execute(
                    f"INSERT INTO pending_commands ({col_str}) VALUES ({placeholders})",
                    [row_dict[c] for c in cols]
                )
                count += 1
            local_conn.commit()
            return count
    except Exception as e:
        logger.error("[SYNC] pull_pending_commands failed: %s", e)
        return 0
```

Call `pull_pending_commands()` at the START of each sync cycle (before the
normal push sync), so commands are pulled down immediately.

**File:** `src/scheduler/watch.py`

The watch loop needs to poll `pending_commands` from local SQLite and execute
them. Find the Telegram command polling block (~line 1590). After it, add:

```python
# 10. Poll dashboard commands from pending_commands table
try:
    from src.commands.executor import poll_and_execute_pending_commands
    poll_and_execute_pending_commands()
except Exception as e:
    logger.debug("[WATCH] Dashboard command polling: %s", e)
```

**File:** `src/commands/executor.py` (NEW FILE — create if it doesn't exist)

```python
"""Execute pending commands from the dashboard command queue.

Called by: scheduler.watch (main loop, every 60s)
Calls: various action handlers based on command_name
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def poll_and_execute_pending_commands(db_path: str = DB_PATH) -> int:
    """Check for pending commands and execute them."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pending_commands WHERE status = 'pending' "
                "ORDER BY priority DESC, created_at ASC LIMIT 1"
            ).fetchall()

        executed = 0
        for row in rows:
            cmd_id = row["command_id"]
            cmd_name = row["command_name"]
            logger.info("[CMD] Executing dashboard command: %s (%s)", cmd_name, cmd_id)

            # Claim the command
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE pending_commands SET status = 'running', "
                    "claimed_at = ? WHERE command_id = ?",
                    (datetime.now(ET).isoformat(), cmd_id)
                )
                conn.commit()

            try:
                result = _execute_command(cmd_name)
                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        "UPDATE pending_commands SET status = 'success' WHERE command_id = ?",
                        (cmd_id,)
                    )
                    # Also write to command_results for the dashboard
                    conn.execute(
                        "INSERT OR REPLACE INTO command_results "
                        "(command_id, status, result_json, completed_at) "
                        "VALUES (?, 'success', ?, ?)",
                        (cmd_id, str(result), datetime.now(ET).isoformat())
                    )
                    conn.commit()
                executed += 1
            except Exception as e:
                logger.error("[CMD] Command %s failed: %s", cmd_name, e)
                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        "UPDATE pending_commands SET status = 'error' WHERE command_id = ?",
                        (cmd_id,)
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO command_results "
                        "(command_id, status, error, completed_at) "
                        "VALUES (?, 'error', ?, ?)",
                        (cmd_id, str(e), datetime.now(ET).isoformat())
                    )
                    conn.commit()

        return executed
    except Exception as e:
        logger.debug("[CMD] poll_and_execute failed: %s", e)
        return 0


def _execute_command(command_name: str) -> dict:
    """Dispatch command to the appropriate handler."""
    if command_name == "scan":
        from src.services.scan_service import run_scan
        return run_scan()
    elif command_name == "stress-test":
        from scripts.stress_test import main as run_stress_test
        return run_stress_test()
    elif command_name == "simulation":
        from src.simulation.engine import run_full_simulation
        return run_full_simulation()
    elif command_name == "validate-system":
        from src.validation.runner import run_validation
        return run_validation()
    elif command_name == "collect-training":
        from src.training.collector import collect_training_data
        return collect_training_data()
    elif command_name == "council":
        from src.council.runner import run_council_session
        return run_council_session()
    elif command_name == "collect-data":
        from src.data_collection.runner import run_all_collectors
        return run_all_collectors()
    elif command_name == "score":
        from src.training.scorer import score_unscored
        return score_unscored()
    elif command_name == "cto-report":
        from src.evaluation.cto_report import generate_cto_report
        return generate_cto_report()
    else:
        raise ValueError(f"Unknown command: {command_name}")
```

**IMPORTANT:** The import paths in `_execute_command` are approximate. Before
implementing, verify each import path exists by grepping the codebase:
```bash
grep -rn "def run_scan\|def run_full_simulation\|def run_validation" src/ scripts/ | head -10
```

**Test:** `test_poll_and_execute_pending_commands` — Insert a mock command
into pending_commands, call `poll_and_execute_pending_commands()`, verify
status changes to 'success' or 'error'.

---

## Root Cause C: Display & Sync Issues (4 tasks)

### Task 5: Fix version string in Layout.jsx

**Problem:** Header shows `v0.15.0` but actual version is `v0.15.3`.

**File:** `frontend/src/components/Layout.jsx`

**Find:**
```javascript
const version = 'v0.15.0'
```

**Replace with dynamic version from the status API:**
```javascript
const version = status?.version || 'v0.15.3'
```

Where `status` is the existing useQuery result already in the component.
Check if the `/api/status` endpoint returns a `version` field. If not, add it
to the status endpoint.

**File:** `src/api/cloud_routes/core.py` — in the status endpoint, ensure
`version` is included in the response. Derive from MASTER.md or hardcode
as `"v0.15.3"` for now (it changes rarely enough).

**Test:** Visual verification — header should show v0.15.3.

---

### Task 6: Fix NEE Postgres upsert type error

**Problem:** Postgres sync fails for NEE with: `"Sync failed for shadow_trades
'long', 'open', '92.920655'"` — numeric values arriving as strings.

**File:** `src/sync/render_sync.py`

**Find the upsert logic** that builds the INSERT/UPDATE statement for
`shadow_trades`. Add type coercion for numeric columns before the upsert:

```python
# Before building the upsert SQL, coerce numeric fields
NUMERIC_COLUMNS = {
    "actual_entry_price", "actual_exit_price", "pnl_dollars", "pnl_pct",
    "planned_shares", "stop_price", "target_price", "duration_days",
    "priority_score", "confidence_score", "position_size_dollars",
    "position_size_pct", "estimated_dollar_risk", "pullback_depth_pct", "atr",
}

for col in NUMERIC_COLUMNS:
    if col in row and row[col] is not None:
        try:
            row[col] = float(row[col])
        except (ValueError, TypeError):
            pass
```

Place this in the sync function BEFORE the Postgres execute call,
specifically in the upsert path for shadow_trades (and ideally for all tables
as a defensive measure).

**Test:** `test_numeric_coercion_in_sync` — Pass a shadow_trade row with
`actual_entry_price="92.920655"` (string), verify it's coerced to float
before upsert.

---

### Task 7: Fix quality score display on CTO Report

**Problem:** CTO Report shows "Quality scoring not yet applied" despite
979 scored examples existing locally (avg 3.4/5).

**File:** `src/api/cloud_routes/analytics.py` — in the cto_report endpoint

**Check how `rubric_score` / `avg_rubric_score` is computed.** The headline KPI
for "RUBRIC SCORE" likely reads from `headline_kpis.avg_rubric_score`. Find
where this is set and verify it queries `COALESCE(quality_score_auto, quality_score)`.

If the value is always NULL in Postgres, the issue is that quality scores are
being written to local SQLite but not syncing. Verify:
1. `training_examples.quality_score_auto` is in the synced columns
2. The sync mode for training_examples is `incremental` with a time column
   that gets updated when scores are written

**Quick fix if scores aren't syncing:** In the scoring function, after writing
`quality_score_auto` to local SQLite, ensure the row's `updated_at` is touched
so the incremental sync picks it up.

**Test:** Verify `quality_score_auto` values exist in Postgres training_examples.

---

### Task 8: Ensure data collectors are running and syncing

**Problem:** SEC EDGAR 7d stale, Insider Transactions 7d stale, Fed Comms 12d
stale, Short Interest never collected.

This is likely a **local machine issue** — the overnight collectors aren't
firing, or they're failing silently. CC cannot fully fix this remotely, but
can add defensive improvements:

**File:** `src/scheduler/overnight.py` — `run_data_collection()`

Add explicit error logging per collector so failures are visible:

```python
def run_data_collection(db_path: str = DB_PATH, collector_failures=None):
    """Run all overnight data collectors with per-collector error isolation."""
    collectors = [
        ("earnings_calendar", _collect_earnings),
        ("edgar_filings", _collect_edgar),
        ("insider_transactions", _collect_insider),
        ("fed_communications", _collect_fed_comms),
        ("short_interest", _collect_short_interest),
        # ... etc
    ]
    for name, func in collectors:
        try:
            func(db_path)
            logger.info("[COLLECT] %s: success", name)
        except Exception as e:
            logger.error("[COLLECT] %s: FAILED — %s", name, e)
            if collector_failures is not None:
                collector_failures[name] = str(e)
```

If the collectors don't follow this pattern, refactor them to do so. Each
collector should be independently try/excepted so one failure doesn't
block the others.

**Also verify:** `run_data_collection()` is called in the watch loop overnight
schedule. Check that the time window (typically 9:30 PM ET) is correct and
that the `done_data_collection` flag resets at midnight.

**Test:** `test_data_collection_isolation` — Mock one collector to raise, verify
others still run.

---

## Post-Sprint Verification

```bash
# 1. Run tests
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py

# 2. Build frontend
cd frontend && npm run build && cd ..

# 3. Verify no new files over 400 lines
find src/ -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); [ "$lines" -gt 400 ] && echo "⚠️  $1: $lines lines"' _ {} \;

# 4. Run new tests specifically
python -m pytest tests/test_dashboard_hotfix.py -v
```

---

## Commit & Tag

```bash
git add -A
git commit -m "fix: dashboard data integrity — 8 tasks across 5 root causes

Root Cause A (CTO Report bugs):
- Fix targets_hit_pct: 'target_1' → 'target_1_hit' (was always 0%)
- Add 7 missing fund metrics (skewness, best/worst, batting avg, etc.)
- Write market_regime to recommendations (was always NULL → 'unknown')

Root Cause B (Command queue):
- Enable pending_commands sync (Postgres → local)
- Add pull_pending_commands to sync cycle
- New src/commands/executor.py: polls + dispatches dashboard commands

Root Cause C (Display/sync):
- Layout.jsx version: 'v0.15.0' → dynamic from API
- Fix NEE upsert: coerce numeric strings to float before Postgres INSERT
- Fix quality score sync: ensure updated_at touched on score write
- Add per-collector error isolation in data_collection

v0.16.0"

git push origin fix/dashboard-data-integrity
```

After PR merge:
```bash
git checkout main
git pull origin main
git tag v0.16.0
git push origin v0.16.0
```

---

## Documentation Update

Update `MASTER.md` Section 2:
- Version: v0.16.0
- GitHub issues: note these 8 fixes
- Dashboard pages: note data integrity improvements

Update `CHANGELOG.md` with the 8 fixes grouped by root cause.

---

## Ralph Loop Notes

### Iteration 1
- Initial spec covered bugs A (3 tasks) and display issues (version, NEE).
- MISSED: Command queue is the reason simulation/stress-test buttons don't
  work — pending_commands isn't synced. Added Task 4 with new executor.py.
- MISSED: Quality score display — added Task 7.
- MISSED: Data collectors stale — added Task 8.

### Iteration 2
- Task 4 (command executor): Import paths in `_execute_command` are
  approximate — added explicit instruction for CC to grep and verify each
  import before implementing. Also added `command_results` write so the
  dashboard can show success/error status.
- Task 6 (NEE upsert): Made the numeric coercion generic with a
  `NUMERIC_COLUMNS` set rather than just fixing NEE — this prevents the
  same bug for any ticker with string-typed numeric fields.
- Task 3 (market_regime): Added verification step — need to confirm
  `compute_market_regime()` output is available in the features dict at
  the point `log_recommendation()` is called. If it's computed but stored
  under a different key (e.g., "regime" vs "market_regime"), the fix needs
  to use the correct key.

### Iteration 3
- Task 2 (fund metrics): Added `avg_mfe_winners: None` with comment — MFE
  tracking requires intraday high/low data that the system doesn't
  currently store. Setting to None with a clear comment is better than
  computing a wrong value. Future sprint can add MFE tracking.
- Task 1 (targets filter): Added both old and new exit_reason values
  for backward compatibility — older trades from before the `_hit` suffix
  convention may exist.
- Task 4: Noted that `pull_pending_commands` must be called BEFORE the
  normal push sync, not after — otherwise there's a 60-second latency on
  command pickup.
- Task 8: Acknowledged this is partially a local-machine issue. CC can
  add error isolation and logging, but Ryan needs to verify the watch loop
  is running with `--overnight` flag and check `logs/arcis.log` for
  collector errors.
- Verified: All 8 tasks touch different functions/files, so they can be
  implemented in any order without conflicts.
