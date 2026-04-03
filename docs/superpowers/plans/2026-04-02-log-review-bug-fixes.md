# Log Review Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 validated bugs (#195, #196, #198, #199) found during log review, shipped as two PRs.

**Architecture:** PR 1 is a one-line type cast fix. PR 2 adds resilience to three subsystems: shadow trading exit retry (cancel before retry), VRAM inference handoff (aggressive cleanup), and Render sync (per-table Postgres reconnection). All fixes are additive — happy paths unchanged.

**Tech Stack:** Python 3.12, SQLite, psycopg2, alpaca-py SDK, torch.cuda, subprocess

**Test Baseline:** 1,225 passed, 48 failed, 17 errors, 5 skipped (2026-04-02). Must not regress.

**Spec:** `docs/superpowers/specs/2026-04-02-log-review-bug-fixes-design.md`

---

## PR 1: Quick Win — pnl_dollars TypeError (#195)

### Task 1: Fix pnl_dollars type cast and add test

**Files:**
- Modify: `src/training/data_collector.py:168`
- Modify: `src/training/data_collector.py:78`
- Modify: `tests/test_data_collectors.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data_collectors.py`:

```python
# ── Training Data Collector: pnl type safety (#195) ───────────────

class TestTrainingDataCollectorPnlTypeSafety:
    """Verify numeric fields from SQLite are cast before comparison (#195)."""

    def test_pnl_dollars_as_string_does_not_raise(self, tmp_db):
        """SQLite may return pnl_dollars as a string — must not TypeError."""
        from src.training.data_collector import collect_training_examples_from_closed_trades

        # Set up minimal schema for the function
        conn = sqlite3.connect(tmp_db)
        conn.execute("""
            CREATE TABLE shadow_trades (
                trade_id TEXT PRIMARY KEY, recommendation_id TEXT,
                ticker TEXT, status TEXT, pnl_dollars TEXT,
                pnl_pct TEXT, exit_reason TEXT, duration_days TEXT,
                max_favorable_excursion TEXT, max_adverse_excursion TEXT,
                actual_exit_time TEXT, created_at TEXT, updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE recommendations (
                recommendation_id TEXT PRIMARY KEY, ticker TEXT,
                enriched_prompt TEXT, created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE training_examples (
                example_id TEXT PRIMARY KEY, recommendation_id TEXT
            )
        """)
        # Insert a closed trade with STRING pnl_dollars (the bug trigger)
        conn.execute(
            "INSERT INTO shadow_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("t1", "r1", "AAPL", "closed", "50.25", "3.2",
             "target_1_hit", "5", "60.0", "10.0",
             "2026-01-05T16:00:00", "2026-01-01", "2026-01-05"),
        )
        conn.execute(
            "INSERT INTO recommendations VALUES (?,?,?,?)",
            ("r1", "AAPL", "Test prompt content", "2026-01-01"),
        )
        conn.commit()
        conn.close()

        # Should NOT raise TypeError: '>' not supported between str and int
        with patch("src.training.data_collector.load_config",
                   return_value={"training": {"enabled": True}}), \
             patch("src.training.data_collector.init_training_tables"), \
             patch("src.training.data_collector.generate_training_example",
                   return_value="Mock analysis output"), \
             patch("src.training.data_collector.validate_training_example",
                   return_value=(True, None)), \
             patch("src.training.data_collector.DB_PATH", tmp_db):
            # This is the line that raises TypeError without the fix
            count = collect_training_examples_from_closed_trades(db_path=tmp_db)

        # Should complete without error (count may be 0 or 1 depending on store)
        assert isinstance(count, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_collectors.py::TestTrainingDataCollectorPnlTypeSafety -v`
Expected: FAIL with `TypeError: '>' not supported between instances of 'str' and 'int'`

- [ ] **Step 3: Fix the type casts in data_collector.py**

In `src/training/data_collector.py`, line 78, change:

```python
P&L: ${trade.get('pnl_dollars', 0):.2f} ({trade.get('pnl_pct', 0):.1f}%)
Duration: {trade.get('duration_days', 0)} days
MFE: ${trade.get('max_favorable_excursion', 0):.2f} | MAE: ${trade.get('max_adverse_excursion', 0):.2f}"""
```

to:

```python
P&L: ${float(trade.get('pnl_dollars') or 0):.2f} ({float(trade.get('pnl_pct') or 0):.1f}%)
Duration: {int(trade.get('duration_days') or 0)} days
MFE: ${float(trade.get('max_favorable_excursion') or 0):.2f} | MAE: ${float(trade.get('max_adverse_excursion') or 0):.2f}"""
```

In `src/training/data_collector.py`, line 168, change:

```python
pnl = trade.get("pnl_dollars", 0) or 0
```

to:

```python
pnl = float(trade.get("pnl_dollars") or 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_collectors.py::TestTrainingDataCollectorPnlTypeSafety -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -q --tb=no`
Expected: >= 1,225 passed, no new failures

- [ ] **Step 6: Commit**

```bash
git checkout -b fix/195-pnl-type-cast
git add src/training/data_collector.py tests/test_data_collectors.py
git commit -m "fix: cast pnl_dollars and numeric fields to float before comparison (#195)

SQLite may return numeric columns as strings. The comparison
pnl > 0 raises TypeError when pnl is a string. Apply defensive
float()/int() casts to all numeric fields from closed trade rows."
```

- [ ] **Step 7: Push and create PR**

```bash
git push -u origin fix/195-pnl-type-cast
gh pr create --title "fix: cast pnl_dollars to float before comparison (#195)" \
  --body "## Summary
- Cast pnl_dollars and other numeric fields from SQLite to float/int before comparison
- Fixes TypeError that blocks overnight training data collection
- Added test verifying string-typed pnl_dollars does not raise

## Test plan
- [ ] New test passes: TestTrainingDataCollectorPnlTypeSafety
- [ ] Full suite: pass count >= 1225, no new failures

Closes #195"
```

---

## PR 2: Structural Reliability (#196, #198, #199)

### Task 2: Add per-table Postgres reconnection to render_sync (#199)

**Files:**
- Modify: `src/sync/render_sync.py:465-519`
- Modify: `tests/test_render_sync.py` (append new test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_sync.py`:

```python
# ── Per-table reconnection tests (#199) ──────────────────────────────

class TestPerTableReconnection:
    """Verify sync cycle recovers from mid-cycle connection failures (#199)."""

    def test_healthy_connection_reused_without_reconnect(self, test_db):
        """When connection stays alive, no reconnection should happen."""
        _init_sync_state(test_db)
        mock_psycopg2 = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_psycopg2.connect.return_value = mock_conn

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            summary = run_sync_cycle("postgresql://test@localhost/db", test_db)

        # connect called exactly once (initial connection, no reconnects)
        assert mock_psycopg2.connect.call_count == 1

    def test_dead_connection_triggers_reconnect(self, test_db):
        """When connection dies mid-cycle, should reconnect for remaining tables."""
        _init_sync_state(test_db)
        mock_psycopg2 = MagicMock()

        # First connection dies on cursor use, second works
        dead_conn = MagicMock()
        dead_cursor_ctx = MagicMock()
        dead_cursor = MagicMock()
        dead_cursor.execute.side_effect = Exception("connection already closed")
        dead_cursor_ctx.__enter__ = MagicMock(return_value=dead_cursor)
        dead_cursor_ctx.__exit__ = MagicMock(return_value=False)
        dead_conn.cursor.return_value = dead_cursor_ctx

        live_conn = MagicMock()
        live_cursor_ctx = MagicMock()
        live_cursor = MagicMock()
        live_cursor_ctx.__enter__ = MagicMock(return_value=live_cursor)
        live_cursor_ctx.__exit__ = MagicMock(return_value=False)
        live_conn.cursor.return_value = live_cursor_ctx

        mock_psycopg2.connect.side_effect = [dead_conn, live_conn]

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            summary = run_sync_cycle("postgresql://test@localhost/db", test_db)

        # Should have reconnected at least once
        assert mock_psycopg2.connect.call_count >= 2

    def test_fully_unreachable_postgres_fails_gracefully(self, test_db):
        """When Postgres is completely down, each table fails independently."""
        _init_sync_state(test_db)
        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            summary = run_sync_cycle("postgresql://test@localhost/db", test_db)

        # Should have errors but not crash
        assert len(summary["errors"]) > 0
        assert "timestamp" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_render_sync.py::TestPerTableReconnection -v`
Expected: At least `test_dead_connection_triggers_reconnect` fails (current code doesn't reconnect)

- [ ] **Step 3: Add _ensure_pg_connection and modify run_sync_cycle**

In `src/sync/render_sync.py`, add the new helper function after `_connect_pg_with_retry` (after line 481):

```python
def _ensure_pg_connection(conn, database_url: str):
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

Then modify `run_sync_cycle` (lines 505-514). Replace:

```python
    try:
        for table_name, table_config in SYNC_TABLES.items():
            try:
                count = sync_table(pg_conn, table_name, table_config, db_path)
                if count > 0:
                    summary["synced"][table_name] = count
                    logger.info("Synced %d rows to %s", count, table_name)
            except Exception as exc:
                logger.error("Sync failed for %s: %s", table_name, exc)
                summary["errors"].append(f"{table_name}: {exc}")
    finally:
        try:
            pg_conn.close()
        except Exception:
            pass
```

with:

```python
    try:
        for table_name, table_config in SYNC_TABLES.items():
            try:
                pg_conn = _ensure_pg_connection(pg_conn, database_url)
                count = sync_table(pg_conn, table_name, table_config, db_path)
                if count > 0:
                    summary["synced"][table_name] = count
                    logger.info("Synced %d rows to %s", count, table_name)
            except Exception as exc:
                logger.error("Sync failed for %s: %s", table_name, exc)
                summary["errors"].append(f"{table_name}: {exc}")
                pg_conn = None  # Force reconnect on next table
    finally:
        if pg_conn:
            try:
                pg_conn.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run reconnection tests to verify they pass**

Run: `python -m pytest tests/test_render_sync.py::TestPerTableReconnection -v`
Expected: PASS

- [ ] **Step 5: Run all render_sync tests**

Run: `python -m pytest tests/test_render_sync.py -v`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git checkout -b fix/reliability-exit-cancel-vram-sync
git add src/sync/render_sync.py tests/test_render_sync.py
git commit -m "fix: add per-table Postgres reconnection in render sync (#199)

If the Postgres connection drops mid-cycle, remaining tables now
reconnect instead of all failing with 'connection already closed'.
Uses SELECT 1 heartbeat before each table sync."
```

---

### Task 3: Add aggressive cleanup to VRAM inference handoff (#198)

**Files:**
- Modify: `src/scheduler/vram_manager.py:160-295`
- Modify: `tests/test_vram_manager.py` (append new tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_vram_manager.py`:

```python
# ── VRAM inference handoff escalation (#198) ────────────────────────


def test_handoff_to_inference_escalates_when_vram_not_clear():
    """When VRAM stays high after training kill, should kill Ollama processes (#198)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    # Simulate training process that exits cleanly
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    vm._training_process = mock_proc

    # nvidia-smi always reports high VRAM (above 1500MB threshold)
    mock_smi = MagicMock()
    mock_smi.returncode = 0
    mock_smi.stdout = "5000\n"

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("subprocess.run", return_value=mock_smi) as mock_run, \
         patch("subprocess.Popen"), \
         patch("requests.post", return_value=mock_resp), \
         patch("time.sleep"):
        result = vm.handoff_to_inference()

    # Should have attempted to kill Ollama processes (taskkill or pkill)
    kill_calls = [c for c in mock_run.call_args_list
                  if any("taskkill" in str(a) or "pkill" in str(a)
                         for a in c.args + tuple(c.kwargs.values()))]
    assert len(kill_calls) > 0, "Should have called taskkill/pkill to kill Ollama"


def test_handoff_to_inference_returns_false_after_escalation_failure():
    """When aggressive cleanup also fails, should return False (#198)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    # nvidia-smi always reports high VRAM
    mock_smi = MagicMock()
    mock_smi.returncode = 0
    mock_smi.stdout = "5000\n"

    with patch("subprocess.run", return_value=mock_smi), \
         patch("subprocess.Popen"), \
         patch("requests.post", side_effect=Exception("Connection refused")), \
         patch("time.sleep"):
        result = vm.handoff_to_inference()

    assert result is False


def test_handoff_to_inference_no_escalation_on_clean_vram():
    """When VRAM clears normally, should NOT kill Ollama processes (#198)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp), \
         patch("src.llm.client.is_llm_available", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("time.sleep"):
        result = vm.handoff_to_inference()

    assert result is True
    # Should NOT have called taskkill/pkill
    kill_calls = [c for c in mock_run.call_args_list
                  if any("taskkill" in str(a) or "pkill" in str(a)
                         for a in c.args + tuple(c.kwargs.values()))]
    assert len(kill_calls) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vram_manager.py::test_handoff_to_inference_escalates_when_vram_not_clear tests/test_vram_manager.py::test_handoff_to_inference_returns_false_after_escalation_failure -v`
Expected: FAIL (no escalation logic exists yet)

- [ ] **Step 3: Extract _kill_ollama_processes from handoff_to_training**

In `src/scheduler/vram_manager.py`, extract the kill logic from `handoff_to_training` (lines 186-200) into a standalone method. Add this method to the `VRAMManager` class, before `handoff_to_training`:

```python
    def _kill_ollama_processes(self) -> None:
        """Force-kill all Ollama processes to reclaim VRAM."""
        try:
            import platform
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                               capture_output=True, timeout=10)
                subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"],
                               capture_output=True, timeout=10)
            else:
                subprocess.run(["pkill", "-f", "ollama"],
                               capture_output=True, timeout=10)
            time.sleep(5)
        except Exception as kill_err:
            logger.warning("[VRAM] Failed to kill Ollama: %s", kill_err)
```

Then replace the inline kill block in `handoff_to_training` (lines 186-200) with:

```python
                self._kill_ollama_processes()
```

- [ ] **Step 4: Add escalation to handoff_to_inference**

In `src/scheduler/vram_manager.py`, replace the `handoff_to_inference` VRAM check block (lines 263-266):

```python
        # Step 2: Verify VRAM clear
        if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=30):
            logger.warning("[VRAM] VRAM not clear after killing training process")
            # Continue anyway — Ollama may still be able to load
```

with:

```python
        # Step 2: Verify VRAM clear — escalate if needed
        if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=30):
            logger.warning("[VRAM] VRAM not clear after 30s — escalating cleanup")

            # Kill Ollama processes to free VRAM (same as training handoff)
            self._kill_ollama_processes()

            # Clear GPU cache again after kills
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("[VRAM] torch.cuda.empty_cache() called after Ollama kill")
            except ImportError:
                pass

            if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=45):
                logger.error("[VRAM] Handoff to inference FAILED — VRAM not clear after aggressive cleanup")
                return False
```

- [ ] **Step 5: Run VRAM tests to verify they pass**

Run: `python -m pytest tests/test_vram_manager.py -v`
Expected: All tests pass including the 3 new ones

- [ ] **Step 6: Commit**

```bash
git add src/scheduler/vram_manager.py tests/test_vram_manager.py
git commit -m "fix: add aggressive VRAM cleanup to inference handoff (#198)

Extract _kill_ollama_processes() and reuse in both handoff paths.
When VRAM doesn't clear after training kill, escalate: kill Ollama,
clear GPU cache, wait 45s. Return False on unrecoverable failure
instead of silently continuing."
```

---

### Task 4: Add cancel_paper_order to Alpaca adapter (#196)

**Files:**
- Modify: `src/shadow_trading/alpaca_adapter.py:331-336`
- Modify: `tests/test_executor_import.py` (expand with adapter tests)

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_executor_import.py` with:

```python
"""Tests for shadow trading executor and adapter (#196)."""

from unittest.mock import patch, MagicMock

import pytest


def test_module_imports():
    """Verify module imports without error."""
    import src.shadow_trading.executor  # noqa: F401


# ── Cancel order adapter (#196) ──────────────────────────────────────


class TestCancelPaperOrder:
    """Test the cancel_paper_order adapter function."""

    def test_cancel_success(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        mock_client = MagicMock()
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result is True
        mock_client.cancel_order_by_id.assert_called_once_with("order-123")

    def test_cancel_already_filled(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        mock_client = MagicMock()
        mock_client.cancel_order_by_id.side_effect = Exception("order already filled")
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result is False

    def test_cancel_no_client(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   side_effect=Exception("No API key")):
            result = cancel_paper_order("order-123")

        assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_executor_import.py::TestCancelPaperOrder -v`
Expected: FAIL with `ImportError: cannot import name 'cancel_paper_order'`

- [ ] **Step 3: Add cancel_paper_order to alpaca_adapter.py**

In `src/shadow_trading/alpaca_adapter.py`, after `get_order_status` (after line 335), add:

```python
def cancel_paper_order(order_id: str) -> bool:
    """Cancel a pending paper order by ID.

    Returns True if canceled successfully, False if already filled/canceled or on error.
    """
    client = _get_trading_client()
    try:
        client.cancel_order_by_id(order_id)
        return True
    except Exception as e:
        logger.warning("[CANCEL] Could not cancel order %s: %s", order_id, e)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_executor_import.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/alpaca_adapter.py tests/test_executor_import.py
git commit -m "feat: add cancel_paper_order to Alpaca adapter (#196)

Thin wrapper around TradingClient.cancel_order_by_id().
Returns True on success, False on error (already filled, etc.).
Follows the same pattern as get_order_status()."
```

---

### Task 5: Add exit_retry_count column to schema registry (#196)

**Files:**
- Modify: `src/schema/registry.py:149-193`

- [ ] **Step 1: Add the column to shadow_trades**

In `src/schema/registry.py`, in the `shadow_trades` table definition, add a new column after `actual_shares` (line 192):

```python
        ColumnDef("actual_shares", "INTEGER"),
        ColumnDef("exit_retry_count", "INTEGER", default="0"),
```

- [ ] **Step 2: Run schema validation**

Run: `python -m src.main validate-schema --fix`
Expected: Schema validated, column added to SQLite

- [ ] **Step 3: Commit**

```bash
git add src/schema/registry.py
git commit -m "schema: add exit_retry_count column to shadow_trades (#196)

Tracks how many times an exit retry has been attempted for a trade.
Used to enforce a max retry limit (3) before abandoning to reconciliation."
```

---

### Task 6: Modify executor to cancel before retry and enforce max retries (#196)

**Files:**
- Modify: `src/shadow_trading/executor.py:386-415`
- Modify: `tests/test_executor_import.py` (append new test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_executor_import.py`:

```python
# ── Exit retry with cancel (#196) ───────────────────────────────────


class TestRetryExitWithCancel:
    """Test that exit retry cancels pending orders before resubmitting (#196)."""

    def test_retry_cancels_pending_order_before_resubmit(self):
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t1",
            "ticker": "PFE",
            "shares": 7,
            "actual_entry_price": 28.0,
            "exit_order_id": "old-order-123",
            "exit_reason": "timeout",
            "exit_retry_count": 0,
        }

        mock_exit_result = {"status": "filled", "filled_avg_price": "29.0"}

        with patch("src.shadow_trading.executor.cancel_paper_order") as mock_cancel, \
             patch("src.shadow_trading.executor._submit_exit_order",
                   return_value=mock_exit_result), \
             patch("src.shadow_trading.executor.close_shadow_trade"), \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("time.sleep"):
            _retry_exit(trade)

        mock_cancel.assert_called_once_with("old-order-123")

    def test_retry_skips_cancel_when_no_pending_order(self):
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t1",
            "ticker": "PFE",
            "shares": 7,
            "actual_entry_price": 28.0,
            "exit_order_id": None,
            "exit_reason": "timeout",
            "exit_retry_count": 0,
        }

        mock_exit_result = {"status": "filled", "filled_avg_price": "29.0"}

        with patch("src.shadow_trading.executor.cancel_paper_order") as mock_cancel, \
             patch("src.shadow_trading.executor._submit_exit_order",
                   return_value=mock_exit_result), \
             patch("src.shadow_trading.executor.close_shadow_trade"), \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("time.sleep"):
            _retry_exit(trade)

        mock_cancel.assert_not_called()

    def test_retry_stops_after_max_retries(self):
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t1",
            "ticker": "PFE",
            "shares": 7,
            "actual_entry_price": 28.0,
            "exit_order_id": "old-order-123",
            "exit_reason": "timeout",
            "exit_retry_count": 3,  # Already at max
        }

        with patch("src.shadow_trading.executor.cancel_paper_order") as mock_cancel, \
             patch("src.shadow_trading.executor._submit_exit_order") as mock_submit, \
             patch("src.shadow_trading.executor.update_shadow_trade") as mock_update, \
             patch("time.sleep"):
            _retry_exit(trade)

        # Should NOT attempt cancel or submit — just mark as abandoned
        mock_cancel.assert_not_called()
        mock_submit.assert_not_called()
        # Should update status to exit_abandoned
        mock_update.assert_called_once()
        update_args = mock_update.call_args
        assert update_args[0][1].get("status") == "exit_abandoned"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_executor_import.py::TestRetryExitWithCancel -v`
Expected: FAIL (cancel_paper_order not imported in executor, no max retry check)

- [ ] **Step 3: Modify _retry_exit in executor.py**

In `src/shadow_trading/executor.py`, add the import near the top of the file (with the other alpaca_adapter imports):

```python
from src.shadow_trading.alpaca_adapter import cancel_paper_order
```

Then replace the `_retry_exit` function (lines 386-415) with:

```python
_MAX_EXIT_RETRIES = 3


def _retry_exit(trade: dict, db_path: str = DB_PATH) -> None:
    """Retry exit for trades stuck in exit_pending or exit_failed.

    Cancels any pending exit order before resubmitting. Gives up after
    _MAX_EXIT_RETRIES attempts and marks the trade as exit_abandoned
    for reconciliation to handle.
    """
    ticker = trade["ticker"]
    retry_count = trade.get("exit_retry_count", 0) or 0

    # Enforce max retry limit
    if retry_count >= _MAX_EXIT_RETRIES:
        logger.error("[RETRY] Max retries (%d) reached for %s — abandoning exit",
                     _MAX_EXIT_RETRIES, ticker)
        update_shadow_trade(trade["trade_id"], {"status": "exit_abandoned"}, db_path)
        return

    # Cancel any existing pending exit order before resubmitting
    pending_order_id = trade.get("exit_order_id") or trade.get("alpaca_order_id")
    if pending_order_id:
        cancel_paper_order(pending_order_id)
        time.sleep(1)  # Brief pause for broker to process cancellation

    # Increment retry counter
    update_shadow_trade(trade["trade_id"],
                        {"exit_retry_count": retry_count + 1}, db_path)

    shares = trade.get("shares", trade.get("planned_shares", 0))
    try:
        exit_result = _submit_exit_order(trade, shares)
        exit_status = exit_result.get("status") if isinstance(exit_result, dict) else None
        if _is_filled_status(exit_status):
            fill_price = float(exit_result.get("filled_avg_price", 0))
            entry_price = trade.get("actual_entry_price") or trade.get("entry_price", 0)
            pnl_dollars = (fill_price - entry_price) * shares if entry_price else 0
            pnl_pct = ((fill_price - entry_price) / entry_price * 100) if entry_price else 0
            close_shadow_trade(
                trade["trade_id"],
                exit_price=fill_price,
                exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                exit_reason=trade.get("exit_reason", "retry_exit"),
                pnl_dollars=round(pnl_dollars, 2),
                pnl_pct=round(pnl_pct, 2),
                db_path=db_path,
            )
            logger.info("[RETRY] Successfully closed %s on retry", ticker)
        elif _is_pending_status(exit_status):
            logger.info("[RETRY] Exit still pending for %s (retry %d/%d)",
                        ticker, retry_count + 1, _MAX_EXIT_RETRIES)
        else:
            update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
            logger.warning("[RETRY] Exit retry failed for %s (status=%s)", ticker, exit_status)
    except Exception as e:
        update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
        logger.error("[RETRY] Exit retry exception for %s: %s", ticker, e)
```

- [ ] **Step 4: Run executor tests to verify they pass**

Run: `python -m pytest tests/test_executor_import.py -v`
Expected: All tests pass

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q --tb=no`
Expected: >= 1,225 passed, no new failures

- [ ] **Step 6: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_executor_import.py
git commit -m "fix: cancel pending exit orders before retry, add max retry limit (#196)

_retry_exit now cancels the existing pending order via
cancel_paper_order() before submitting a new one. After 3 failed
retries, marks the trade as exit_abandoned for reconciliation.
Prevents duplicate exit orders that caused PFE -14 shares (#188)."
```

---

### Task 7: Final validation and PR

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -q --tb=short`
Expected: >= 1,225 passed, no new failures beyond baseline (48 failed, 17 errors)

- [ ] **Step 2: Run schema validation**

Run: `python -m src.main validate-schema`
Expected: All 46 tables validated, no drift

- [ ] **Step 3: Push and create PR**

```bash
git push -u origin fix/reliability-exit-cancel-vram-sync
gh pr create --title "fix: reliability improvements — exit cancel, VRAM handoff, sync reconnection" \
  --body "## Summary
- **#196**: Cancel pending exit orders before retry, enforce 3-retry max
- **#198**: Add aggressive VRAM cleanup to inference handoff (kill Ollama, cache clear)
- **#199**: Per-table Postgres reconnection in render sync cycle

## Test plan
- [ ] TestPerTableReconnection: 3 scenarios pass
- [ ] test_handoff_to_inference_escalates_when_vram_not_clear passes
- [ ] test_handoff_to_inference_returns_false_after_escalation_failure passes
- [ ] test_handoff_to_inference_no_escalation_on_clean_vram passes
- [ ] TestCancelPaperOrder: 3 tests pass
- [ ] TestRetryExitWithCancel: 3 tests pass
- [ ] Full suite: pass count >= 1225, no new failures
- [ ] validate-schema passes

Closes #196, closes #198, closes #199"
```
