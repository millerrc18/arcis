# Arcis Log Audit: 2026-04-03 RCCA Report

**Audited by:** Claude Opus 4.6 (1M context)
**Date:** 2026-04-03
**Log file:** `logs/arcis.log` (760 lines for 2026-04-03)
**Scope:** All ERROR, WARNING, and failure entries from the 24-hour period

---

## Executive Summary

Eight distinct issues were identified from the 4/3 log. Six are active bugs impacting trading operations. The single largest systemic root cause is **TEXT-typed columns in SQLite being used in numeric operations without casting** -- this one design flaw is responsible for Issues 1, 3, 6, and 8. The remaining issues are a missing function argument (Issue 2b), an undefined variable (Issue 5), and Postgres sync logic bugs (Issue 4).

**Impact during 4/3:**
- Position monitor (stop-losses, targets, timeouts) was non-functional for all 37 open shadow + 4 live positions from 09:05 onward
- No email briefings were delivered (pre-market brief, pre-market digest, midday digest all failed)
- VIX and market regime data were stale all day; council ran without fresh regime context
- HSHS performance sub-score was missing from all council evaluations
- Postgres sync failed for 5 tables on every cycle (~18 cycles), accumulating ~180 errors
- Telegram startup notifications failed every hour

---

## Systemic Root Cause: TEXT Columns in Numeric Operations

### Why this keeps happening

The `shadow_trades` table (and others like `scan_metrics`, `vix_term_structure`) define columns as REAL or INTEGER in `src/schema/registry.py`, but SQLite's dynamic typing does not enforce column types. Values inserted as strings (e.g., `"45.50"` instead of `45.50`) remain strings permanently. When application code retrieves these values and performs comparisons (`<=`, `>=`), arithmetic (`-`, `+`, `*`), or math functions (`abs()`), Python raises `TypeError`.

### Why `or 0` fallbacks don't help

A common pattern in the codebase is `value = row["col"] or 0`. This does NOT cast to a number -- it only substitutes `0` for falsy values (`None`, `""`, `0`, `False`). A string like `"5.25"` is truthy and passes through unchanged.

### Permanent fix recommendation

Introduce a defensive cast at the data access layer. Options:
1. A custom `sqlite3.Row` factory that casts based on schema column types from the registry
2. A helper function like `_num(val, default=0.0) -> float` used at every retrieval point
3. A data migration to convert all existing TEXT values to their proper types, combined with stricter INSERT logic

The existing `_parse_price()` helper in `src/shadow_trading/executor.py:33-43` already handles string-to-float conversion for price values -- it just isn't used at DB retrieval points.

---

## Issue 1: Position Monitor Completely Broken (CRITICAL)

### Symptoms
- **17 occurrences** of each error, every ~16 minutes from 09:05 through end of day
- Both paper and live trade management non-functional
```
[POSITION] Paper trade management failed: '<=' not supported between instances of 'str' and 'int'
[POSITION] Live trade check failed: '<=' not supported between instances of 'str' and 'int'
```

### Impact
All 33 open shadow positions and 4 live positions were **unmanaged** during market hours. Stop-losses were not evaluated. Targets were not checked. Timeouts were not enforced.

### Root Cause
**File:** `src/shadow_trading/executor.py`

Database values from the `shadow_trades` table are retrieved as TEXT strings and compared directly against numeric literals without type conversion.

### Affected Code Locations

**Primary comparison failures (the lines that actually crash):**

| Line | Code | DB Column | Fix |
|------|------|-----------|-----|
| 430 | `if retry_count >= _MAX_EXIT_RETRIES:` | `exit_retry_count` | `int(trade.get("exit_retry_count", 0) or 0)` |
| 523 | `if entry_price <= 0:` | `actual_entry_price` / `entry_price` | `float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)` |
| 661 | `if current_price <= stop_price and stop_price > 0:` | `stop_price` | `float(trade.get("stop_price") or 0)` |
| 663 | `elif current_price >= target_2 and target_2 > 0:` | `target_2` | `float(trade.get("target_2") or 0)` |
| 665 | `elif current_price >= target_1 and target_1 > 0:` | `target_1` | `float(trade.get("target_1") or 0)` |

**Secondary arithmetic failures (would crash once comparisons are fixed):**

| Line | Code | DB Column | Fix |
|------|------|-----------|-----|
| 446 | `shares = trade.get("shares", trade.get("planned_shares", 0))` | `shares`, `planned_shares` | Wrap in `int()` |
| 453 | `pnl_dollars = (fill_price - entry_price) * shares` | Derived from above | Already fixed if retrieval is cast |
| 534 | `shares = trade.get("planned_shares", 1)` | `planned_shares` | `int(trade.get("planned_shares") or 1)` |
| 1019 | `risk_per_share = entry_price - stop_price` | Derived | Already fixed if retrieval is cast |

**Retrieval points where casts must be applied (lines 518-521):**
```python
# CURRENT (broken):
entry_price = trade.get("actual_entry_price") or trade.get("entry_price", 0)
stop_price = trade.get("stop_price", 0)
target_1 = trade.get("target_1", 0)
target_2 = trade.get("target_2", 0)

# FIXED:
entry_price = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
stop_price = float(trade.get("stop_price") or 0)
target_1 = float(trade.get("target_1") or 0)
target_2 = float(trade.get("target_2") or 0)
```

### Existing Helper
`_parse_price(value)` at lines 33-43 of the same file already handles string-to-float with fallback to 0.0. Extend its use to all price column retrievals.

### Corrective Action
1. Apply `float()` casts at lines 518-521 for all price columns
2. Apply `int()` casts at lines 427, 446, 534 for count/share columns
3. Verify that `_parse_price()` covers edge cases (empty string, None, non-numeric text)
4. Add a regression test that inserts TEXT-typed values into shadow_trades and runs the position monitor

---

## Issue 2a: VIX Refresh Broken

### Symptoms
- **6 occurrences**, recurring hourly from 09:05 onward
```
[SENTIMENT] VIX refresh failed: float() argument must be a string or a real number, not 'Series'
```

### Root Cause
**File:** `src/scheduler/sentiment_scanner.py`
**Line:** 42

```python
vix_data = yf.download("^VIX", period="1d", progress=False)
if vix_data is not None and not vix_data.empty:
    vix_val = float(vix_data["Close"].iloc[-1])  # <-- FAILS HERE
```

The yfinance `download()` function for a single ticker returns a DataFrame where `.iloc[-1]` yields a pandas Series, not a scalar. This is a known yfinance behavior change.

### Corrective Action
Change line 42 to:
```python
vix_val = float(vix_data["Close"].iloc[-1].item())
```

Or switch to the `yf.Ticker("^VIX").history()` pattern already used successfully in `src/data_collection/vix_collector.py:27-37`.

---

## Issue 2b: Market Regime Refresh Broken

### Symptoms
- **6 occurrences**, recurring hourly, always immediately after the VIX failure
```
[SENTIMENT] Regime refresh failed: compute_market_regime() missing 1 required positional argument: 'ohlcv_data'
```

### Root Cause
**File:** `src/scheduler/sentiment_scanner.py`
**Line:** 60

```python
regime = compute_market_regime(spy)  # Missing 2nd required argument
```

**Function signature** at `src/features/regime.py:45`:
```python
def compute_market_regime(spy: pd.DataFrame, ohlcv_data: dict[str, pd.DataFrame]) -> dict:
```

The function requires two arguments. Every other caller in the codebase passes both:
- `src/features/engine.py:180` -- `compute_market_regime(spy, ohlcv_data)`
- `src/journal/store.py:265` -- `compute_market_regime(spy, {})`
- `src/training/historical_scanner.py:52` -- `compute_market_regime(spy_df, ohlcv_dict)`

### Corrective Action
Change line 60 to:
```python
regime = compute_market_regime(spy, {})
```

An empty dict is safe -- the breadth calculation (lines 93-101 of `regime.py`) iterates over `ohlcv_data.items()`, which yields nothing for an empty dict, defaulting breadth to 50%.

---

## Issue 3a: Pre-market Brief Failed

### Symptoms
- **1 occurrence** at 06:00
```
Pre-market brief failed: unsupported operand type(s) for -: 'str' and 'str'
```

### Root Cause
**File:** `src/scheduler/watch.py`
**Line:** 2575

```python
vix = vix_row["vix"] if vix_row else 0.0        # Line 2569 -- TEXT from DB
vix_prev = vix_prev_row["vix"] if vix_prev_row else vix  # Line 2574 -- TEXT from DB
vix_change = vix - vix_prev                       # Line 2575 -- str - str = TypeError
```

The `vix` column in `vix_term_structure` is defined as REAL in `registry.py:858` but stored as TEXT.

### Corrective Action
Cast at retrieval:
```python
vix = float(vix_row["vix"]) if vix_row else 0.0
vix_prev = float(vix_prev_row["vix"]) if vix_prev_row else vix
```

---

## Issue 3b: Pre-market and Midday Digest Emails Failed

### Symptoms
- **2 occurrences** at 07:30 and 12:00
```
Pre-market digest failed: unsupported operand type(s) for +: 'int' and 'str'
Midday digest failed: unsupported operand type(s) for +: 'int' and 'str'
```

### Root Cause
**File:** `src/email/digest_builder.py`
**Lines:** 153-157

```python
total_packets = sum(s["packet_worthy"] or 0 for s in scans)   # Line 153
total_traded = sum(s["paper_traded"] or 0 for s in scans)     # Line 154
llm_success = sum(s["llm_success"] or 0 for s in scans)       # Line 155
llm_total = sum(s["llm_total"] or 0 for s in scans)           # Line 156
```

The `scan_metrics` table columns (`packet_worthy`, `paper_traded`, `llm_success`, `llm_total`) are defined as INTEGER in `registry.py:1054-1065` but stored as TEXT. Python's `sum()` starts with accumulator `0` (int) and tries to add `"5"` (str), raising TypeError.

The `or 0` fallback does NOT fix this: `"5" or 0` evaluates to `"5"` because non-empty strings are truthy.

### Corrective Action
Cast inside the sum generators:
```python
total_packets = sum(int(s["packet_worthy"] or 0) for s in scans)
total_traded = sum(int(s["paper_traded"] or 0) for s in scans)
llm_success = sum(int(s["llm_success"] or 0) for s in scans)
llm_total = sum(int(s["llm_total"] or 0) for s in scans)
```

---

## Issue 4a: Postgres Schema Drift (stress_test_results + shadow_trades columns)

### Symptoms
- **5 occurrences** each, every sync cycle from ~09:45 onward
```
relation "stress_test_results" does not exist
column "regime_at_entry" of relation "shadow_trades" does not exist
```

### Root Cause
The `stress_test_results` table is defined in `src/schema/registry.py:1353-1380` with `sync_to_postgres=True`. The columns `regime_at_entry`, `regime_at_exit`, `vix_at_entry`, `vix_at_exit` are defined on `shadow_trades` in registry.py:195+. Both exist in local SQLite but `scripts/render_migrate.py` was never executed after they were added.

### Corrective Action
One-time fix:
```bash
DATABASE_URL="<render-postgres-url>" python scripts/render_migrate.py
```
This runs `create_all_tables()` and `ensure_columns()` which are idempotent (IF NOT EXISTS / PL/pgSQL blocks).

---

## Issue 4b: Duplicate Key Violations on Postgres Sync (5 tables, every cycle)

### Symptoms
- **~180 total errors** across the day, 6-7 per sync cycle, every cycle
```
edgar_filings: duplicate key value violates unique constraint "edgar_filings_pkey"
vix_term_structure: duplicate key value violates unique constraint "vix_term_structure_pkey"
macro_snapshots: duplicate key value violates unique constraint "macro_snapshots_pkey"
earnings_calendar: duplicate key value violates unique constraint "idx_earnings_ticker_date"
activity_log: null value in column "id" of relation "activity_log" violates not-null constraint
```

### Root Cause
**File:** `src/sync/render_sync.py`
**Function:** `_upsert_to_postgres()` at lines 210-245

The ON CONFLICT upsert logic has multiple issues depending on the table:

**Table-by-table breakdown:**

| Table | sync_pk | sync_conflict_col | Failure Mode |
|-------|---------|-------------------|--------------|
| `edgar_filings` | `id` (SERIAL) | `accession_number` | ON CONFLICT target doesn't resolve correctly against the UNIQUE INDEX `idx_edgar_accession`; new rows from SQLite have different `id` values that collide with existing Postgres SERIAL ids |
| `vix_term_structure` | `id` (SERIAL) | n/a (`latest_only` mode) | `_replace_latest_in_postgres()` DELETEs then INSERTs, but SERIAL id reuse causes pkey collisions |
| `macro_snapshots` | `id` (SERIAL) | n/a (`latest_only` mode) | Same as vix_term_structure |
| `earnings_calendar` | n/a | **none defined** | No `sync_conflict_col` in registry; no composite unique constraint on `(ticker, earnings_date)`; duplicate rows fail on the index `idx_earnings_ticker_date` that exists in Postgres but isn't referenced in the ON CONFLICT clause |
| `activity_log` | `id` | n/a | Rows inserted in `src/logging/activity.py:56-61` without specifying `id` (relies on SQLite AUTOINCREMENT); when synced to Postgres, `id` is NULL, violating NOT NULL constraint |

**The core bug in `_upsert_to_postgres()`:**
```python
conflict_target = conflict_col or pk  # Falls back to pk if no conflict_col
update_set = ", ".join(
    f"{col} = EXCLUDED.{col}" for col in columns if col != conflict_target
)
sql = (
    f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "
    f"ON CONFLICT ({conflict_target}) DO UPDATE SET {update_set}"
)
```

When `conflict_col` is not defined and `pk` is a SERIAL integer, ON CONFLICT on the SERIAL column is wrong -- it should conflict on the natural/business key, not the surrogate key.

### Corrective Action
1. **`edgar_filings`** in `registry.py`: Verify `sync_conflict_col="accession_number"` is set and that the ON CONFLICT clause correctly references it as a column
2. **`vix_term_structure` / `macro_snapshots`**: Fix `_replace_latest_in_postgres()` to not reuse SERIAL ids, or switch to upsert on a natural key (e.g., `collected_date`)
3. **`earnings_calendar`** in `registry.py`: Add `sync_conflict_col` or a composite unique definition on `(ticker, earnings_date)`
4. **`activity_log`**: Either (a) ensure `id` is populated before sync by using `SELECT rowid as id, ...` from SQLite, or (b) let Postgres generate its own id with `DEFAULT nextval()` and exclude `id` from the INSERT column list during sync
5. **`_upsert_to_postgres()`**: Add validation that `conflict_target` is a real column with a UNIQUE constraint, not just a SERIAL pk

---

## Issue 4c: options_chains Connection Drop (recurring noise)

### Symptoms
- **11 occurrences** throughout the day
```
Sync failed for options_chains: connection already closed
```

### Root Cause
**File:** `src/sync/render_sync.py`
**Function:** `_ensure_pg_connection()` at lines 503-514

The Postgres connection drops during or after syncing the `options_chains` table (which is `sync_mode="latest_only"` and likely transfers large datasets). The connection health check at the start of each table sync doesn't catch connections that die mid-transfer.

### Corrective Action
- Add a try/except around the `options_chains` sync that reconnects on failure
- Or increase the Postgres connection timeout / keepalive settings
- Lower priority -- this is a resilience issue, not a logic bug

---

## Issue 4d: DNS Resolution Failures (transient)

### Symptoms
- **14 warnings** + **3 errors**, mostly between 00:00-04:00
```
could not translate host name "dpg-d72kjk8gjchc7386lsqg-a.virginia-postgres.render.com" to address: Name or service not known
```

### Root Cause
Intermittent DNS resolution failures to the Render Postgres host. Likely ISP/network-level flakiness during off-peak hours. The retry logic (3 attempts) sometimes recovers, sometimes doesn't.

### Corrective Action
- No code change needed -- this is infrastructure/network noise
- The existing 3-retry logic is appropriate
- Consider caching the resolved IP if this becomes persistent

---

## Issue 5: Telegram Notifications Broken

### Symptoms
- **4 occurrences** at hourly intervals (09:59, 11:00, 12:00, 13:01)
```
Telegram startup notification failed: name 'model_name' is not defined
```

### Root Cause
**File:** `src/scheduler/watch.py`
**Line:** 515 (in `_print_status_heartbeat()` method)

```python
def _print_status_heartbeat(self):
    # ...
    try:
        from src.notifications.telegram import notify_system_event, is_telegram_enabled
        if is_telegram_enabled():
            notify_system_event(
                "ARCIS STARTED",
                f"Model: {model_name}\n..."  # <-- model_name is UNDEFINED here
            )
```

The variables `model_name` and `training_str` are defined in a different method (`_print_banner()`, lines 446-461) and are not accessible from `_print_status_heartbeat()`. The banner method imports `get_active_model_name()` from `src/training/versioning` and computes both values, but the heartbeat method skips this.

### Corrective Action
Add variable definitions before the Telegram call in `_print_status_heartbeat()`:
```python
from src.training.versioning import get_active_model_name, get_training_example_counts
model_name = get_active_model_name()
if self.training_enabled:
    t_counts = get_training_example_counts()
    training_str = f"enabled ({t_counts['total']} examples)"
else:
    training_str = "disabled"
```

Or extract the Telegram notification into a shared helper that both methods call.

---

## Issue 6: HSHS Performance Sub-Score Broken

### Symptoms
- **4 occurrences** during council sessions at 08:30 and 08:48
```
[HSHS] performance sub-score error: bad operand type for abs(): 'str'
```

### Impact
Council sessions ran without the HSHS performance sub-score feeding into evaluations. The council still reached consensus (4-1 bearish) but with incomplete scoring data.

### Root Cause
**File:** `src/evaluation/hshs_live.py`
**Line:** 73 (in `_score_performance()` function)

```python
cur = conn.execute(
    "SELECT COALESCE(MIN(pnl_pct), 0) FROM shadow_trades "
    "WHERE status = 'closed'"
)
max_dd = abs(float(cur.fetchone()[0] or 0))
```

The `pnl_pct` column in `shadow_trades` is defined as REAL in `registry.py:169` but stored as TEXT. The `COALESCE(MIN(pnl_pct), 0)` returns a TEXT minimum (string comparison, not numeric), and `abs()` is called on the result.

**Additional latent bugs in the same file that haven't crashed yet but will:**

| Line | Code | Risk |
|------|------|------|
| 76 | `win_rate = winners / total if total else 0` | `total` from `COUNT(*)` should be int, but if aggregation returns text, division fails |
| 79 | `count_score = min(25.0, total * 2.5)` | `total * 2.5` fails if `total` is text |
| 115 | `quality_score = min(35.0, avg_quality * 35)` | `avg_quality` from `AVG(quality_score)` on `training_examples` table -- if any quality_score is TEXT, the AVG may return text |

### Corrective Action
Wrap all DB-retrieved numeric values:
```python
# Line 73:
raw = cur.fetchone()[0]
max_dd = abs(float(raw)) if raw is not None else 0.0

# Line 76:
total = int(cur.fetchone()[0] or 0)

# Line 115:
avg_quality = float(row[0]) if row and row[0] is not None else 0.5
```

---

## Issue 7: Ollama VRAM Handoff Failed (transient, recovered)

### Symptoms
- **1 occurrence** at 05:16, recovered by 07:00
```
05:16 - [VRAM] Beginning handoff to inference...
05:18 - [VRAM] Reload request failed: Read timed out (120s)
05:18 - [VRAM] Handoff to inference FAILED -- Ollama reload failed
05:20 - [VRAM] Reload request failed (again)
07:00 - [LLM] Inference completed in 2.4s -- Ollama warm and responsive
```

### Root Cause
**File:** `src/scheduler/vram_manager.py`

Ollama failed to respond to a model reload request within the 120-second timeout, likely because it was still unloading a training model or the system was under memory pressure during overnight training completion.

### Corrective Action
- No code fix required -- self-healed before market open
- Consider increasing the reload timeout or adding a retry with exponential backoff
- Lower priority

---

## Issue 8: Stale Lockfile (noise, self-healed)

### Symptoms
- **1 occurrence** at 00:23
```
Removing stale lockfile (was PID 37172)
```

### Root Cause
A previous watch loop instance (PID 37172) terminated without cleaning up `data/watch.lock`. The new instance detected and removed it.

### Corrective Action
- No fix needed -- the existing stale-lock detection works correctly
- This is informational only

---

## Priority Order for Fixes

| Priority | Issue | Severity | Effort |
|----------|-------|----------|--------|
| P0 | Issue 1: Position monitor | CRITICAL -- live positions unmanaged | Low (type casts at ~10 retrieval points) |
| P0 | Issue 2a: VIX refresh | HIGH -- stale market data | Trivial (1 line) |
| P0 | Issue 2b: Regime refresh | HIGH -- stale market data | Trivial (1 line) |
| P1 | Issue 3b: Digest emails | HIGH -- no daily reporting | Low (4 lines in digest_builder) |
| P1 | Issue 3a: Pre-market brief | HIGH -- no morning brief | Low (2 lines in watch.py) |
| P1 | Issue 6: HSHS scoring | MEDIUM -- council runs with incomplete data | Low (3-4 lines) |
| P1 | Issue 5: Telegram | MEDIUM -- no startup notifications | Low (5 lines) |
| P2 | Issue 4a: Schema drift | MEDIUM -- sync failures | Trivial (run migrate script) |
| P2 | Issue 4b: Duplicate keys | MEDIUM -- sync data loss | Medium (sync logic rework) |
| P3 | Issue 4c: Connection drops | LOW -- transient failures | Low (retry logic) |

---

## Cross-Cutting Recommendation

Before fixing individual issues, consider a one-time data migration to convert all TEXT values in numeric columns to their proper types:

```sql
-- Example for shadow_trades:
UPDATE shadow_trades SET entry_price = CAST(entry_price AS REAL) WHERE typeof(entry_price) = 'text';
UPDATE shadow_trades SET stop_price = CAST(stop_price AS REAL) WHERE typeof(stop_price) = 'text';
UPDATE shadow_trades SET pnl_pct = CAST(pnl_pct AS REAL) WHERE typeof(pnl_pct) = 'text';
-- ... repeat for all numeric columns stored as TEXT
```

This fixes the data at rest. The code-level casts (described in each issue above) provide defense-in-depth for any future TEXT insertions.

To audit which columns are affected:
```sql
SELECT 'shadow_trades' as tbl, 'entry_price' as col, COUNT(*) as text_count
FROM shadow_trades WHERE typeof(entry_price) = 'text'
UNION ALL
SELECT 'shadow_trades', 'pnl_pct', COUNT(*) FROM shadow_trades WHERE typeof(pnl_pct) = 'text'
-- ... extend for all suspect columns
```
