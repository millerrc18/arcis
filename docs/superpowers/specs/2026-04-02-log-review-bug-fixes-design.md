# Log Review Bug Fixes — Design Spec

**Date:** 2026-04-02
**Issues:** #195, #196, #198, #199 (excluding #197 — Finnhub API key, handled separately)
**Approach:** Two PRs — quick win + structural reliability

## Test Baseline

Captured 2026-04-02:
- **1,225 passed**, 48 failed, 17 errors, 5 skipped
- Pre-existing failures in council, digest builder, traffic light, system validator
- No pre-existing failures in target files

Constraint: pass count must not decrease, failure count must not increase (CLAUDE.md).

---

## PR 1: Quick Win — pnl_dollars TypeError (#195)

**Branch:** `fix/195-pnl-type-cast`

### Problem

`src/training/data_collector.py:175` crashes with `TypeError: '>' not supported between instances of 'str' and 'int'`. The `pnl_dollars` field from SQLite is sometimes a string, and the code compares it to an int without casting.

### Changes

**`src/training/data_collector.py`**

1. Line 168 — cast `pnl_dollars` to float:
   ```python
   # Before:
   pnl = trade.get("pnl_dollars", 0) or 0
   # After:
   pnl = float(trade.get("pnl_dollars") or 0)
   ```

2. Lines ~78-80 — apply same defensive cast to all numeric fields retrieved from SQLite in the same function:
   ```python
   pnl_dollars = float(trade.get("pnl_dollars") or 0)
   pnl_pct = float(trade.get("pnl_pct") or 0)
   duration_days = int(trade.get("duration_days") or 0)
   max_favorable = float(trade.get("max_favorable_excursion") or 0)
   max_adverse = float(trade.get("max_adverse_excursion") or 0)
   ```

**`tests/test_data_collectors.py`**

Add test case:
- Mock a closed trade row where `pnl_dollars` is `"50.25"` (string, as SQLite may return)
- Verify `collect_training_examples_from_closed_trades()` does not raise TypeError
- Verify the numeric comparison correctly classifies the trade as a winner

### Risk

Minimal. Defensive casts on values that should already be numeric. No behavior change for correctly-typed values.

---

## PR 2: Structural Reliability (#196, #198, #199)

**Branch:** `fix/reliability-exit-cancel-vram-sync`

### Fix A: Cancel pending orders before exit retry (#196)

#### Problem

When an exit order returns `PENDING_NEW`, the system retries on the next cycle by submitting a NEW exit order — without canceling the pending one. This creates duplicate orders on the broker, which can result in short positions in a long-only system (root cause of #188).

#### Changes

**`src/shadow_trading/alpaca_adapter.py` — new function:**

```python
def cancel_paper_order(order_id: str) -> bool:
    """Cancel a pending order by ID. Returns True if canceled, False if already filled/canceled."""
    client = _get_trading_client()
    try:
        client.cancel_order_by_id(order_id)
        return True
    except Exception as e:
        logger.warning("[CANCEL] Could not cancel order %s: %s", order_id, e)
        return False
```

Follows the same thin-wrapper pattern as existing `get_order_status()` (~line 331).

**`src/shadow_trading/executor.py` — modify `_retry_exit()` (~line 391):**

Before submitting a new exit order, cancel the previous one:

```python
def _retry_exit(self, trade):
    # Cancel any existing pending exit order first
    pending_order_id = trade.get("exit_order_id")
    if pending_order_id:
        cancel_paper_order(pending_order_id)
        time.sleep(1)  # Brief pause for broker to process cancellation

    # Then submit fresh exit order (existing logic continues here)
    ...
```

**Add max retry limit:**

- Read `exit_retry_count` from the trade's SQLite row (add column to `shadow_trades` in `registry.py` if it doesn't exist, default 0)
- Increment on each `_retry_exit` call via `UPDATE shadow_trades SET exit_retry_count = exit_retry_count + 1`
- After 3 failed retries, log an ERROR, set status to `exit_abandoned`, and stop retrying
- Let daily reconciliation handle stuck positions instead of infinite retry

**`tests/test_executor_import.py` — new tests:**

- Mock `cancel_order_by_id`, verify it's called before retry submit
- Verify max retry limit stops after 3 attempts
- Verify a successful cancel + retry flow completes normally

#### Risk

Medium. Introduces a new broker API call (`cancel_order_by_id`). The Alpaca SDK supports it natively. Failure to cancel is non-fatal (logged as warning, retry still proceeds).

---

### Fix B: VRAM inference handoff aggressive cleanup (#198)

#### Problem

`handoff_to_inference()` in `vram_manager.py` logs a warning when VRAM doesn't clear, then continues anyway. Ollama reload fails because there isn't enough VRAM. The parallel function `handoff_to_training()` has a multi-tier aggressive cleanup (kill Ollama, cache clear, restart) that `handoff_to_inference()` lacks.

#### Changes

**`src/scheduler/vram_manager.py` — modify `handoff_to_inference()` (lines ~264-280):**

After the existing 30s VRAM wait fails, add escalation:

```python
if vram_used > VRAM_THRESHOLD:
    logger.warning("[VRAM] VRAM not clear after 30s: %dMB — escalating", vram_used)

    # Stage 1: Kill Ollama processes (reuse existing logic from training handoff)
    _kill_ollama_processes()
    time.sleep(5)

    # Stage 2: Clear GPU cache again
    torch.cuda.empty_cache()

    # Stage 3: Final wait (45s, matching training handoff)
    if not _wait_for_vram_clear(timeout=45):
        logger.error("[VRAM] Handoff to inference FAILED — VRAM not clear after aggressive cleanup")
        return False

# Restart Ollama fresh (it was killed above)
_ensure_ollama_running()
```

**Refactoring:** If `_kill_ollama_processes()` is currently inline in `handoff_to_training()`, extract it into a standalone private function so both handoff paths can call it. If it's already a function, just call it.

**Return value fix:** Currently `handoff_to_inference()` returns `True` even on VRAM failure. Change to return `False` on final failure so callers can detect and alert.

**`tests/test_vram_manager.py` — new tests:**

- Mock `torch.cuda` and subprocess calls
- Verify escalation triggers only when VRAM stays above threshold (not on happy path)
- Verify `_kill_ollama_processes()` is called in failure path
- Verify `False` is returned on unrecoverable failure

#### Risk

Low. Ports proven logic from the training handoff. Happy path is unchanged. Only the failure path gets new behavior.

---

### Fix C: Render sync per-table Postgres reconnection (#199)

#### Problem

`run_sync_cycle()` opens one Postgres connection and reuses it for all ~20 table syncs. If the connection drops mid-cycle, all remaining tables fail with "connection already closed."

#### Changes

**`src/sync/render_sync.py` — new helper function:**

```python
def _ensure_pg_connection(conn, database_url):
    """Return existing connection if alive, otherwise create a new one."""
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    return _connect_pg_with_retry(database_url)
```

**Modify `run_sync_cycle()` (lines ~496-519):**

```python
pg_conn = _connect_pg_with_retry(database_url)
try:
    for table_name, config in SYNC_TABLES.items():
        try:
            pg_conn = _ensure_pg_connection(pg_conn, database_url)
            sync_table(pg_conn, table_name, config, db_path)
        except Exception as e:
            logger.error("Sync failed for %s: %s", table_name, e)
            pg_conn = None  # Force reconnect on next table
finally:
    if pg_conn:
        pg_conn.close()
```

**`tests/test_render_sync.py` — new tests:**

Three scenarios:
1. **Connection stays alive** — all tables sync with same connection, no reconnect
2. **Connection dies mid-cycle** — reconnects, remaining tables succeed
3. **Postgres fully unreachable** — tables fail individually without cascading, cycle completes gracefully

#### Risk

Low. Additive change. Happy path adds one `SELECT 1` per table (~20 per cycle, negligible). Only the failure path changes behavior. Reuses existing `_connect_pg_with_retry()`.

---

## Implementation Order

Within PR 2, the fixes are independent and can be implemented in any order. Recommended sequence:

1. **Fix C (render sync)** — smallest, most self-contained, easy to verify
2. **Fix B (VRAM)** — may require extracting a helper function, moderate complexity
3. **Fix A (exit cancel)** — new broker interaction, most complex, should be tested most carefully

## Files Modified Summary

| File | PR | Changes |
|------|-----|---------|
| `src/training/data_collector.py` | PR 1 | Type casts on numeric fields |
| `tests/test_data_collectors.py` | PR 1 | String-from-SQLite test case |
| `src/sync/render_sync.py` | PR 2 | `_ensure_pg_connection()` + per-table recovery |
| `tests/test_render_sync.py` | PR 2 | Connection failure scenarios |
| `src/scheduler/vram_manager.py` | PR 2 | Escalation in `handoff_to_inference()`, extract `_kill_ollama_processes()` |
| `tests/test_vram_manager.py` | PR 2 | Escalation path tests |
| `src/schema/registry.py` | PR 2 | Add `exit_retry_count` column to `shadow_trades` table |
| `src/shadow_trading/alpaca_adapter.py` | PR 2 | `cancel_paper_order()` wrapper |
| `src/shadow_trading/executor.py` | PR 2 | Cancel before retry + max retry limit |
| `tests/test_executor_import.py` | PR 2 | Cancel + retry limit tests |
