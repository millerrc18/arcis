# Log Error Rectification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 6 open GitHub issues (#341-#346) found during the comprehensive log review — unblock daily reporting, training collection, earnings refresh, VRAM handoff, broker exit handling, and Render health checks.

**Architecture:** Three phases ordered by impact. Phase 1 fixes the active crashes blocking daily operations (type safety in cto_report.py, data_collector.py format strings, earnings refresh argument, healthz endpoint). Phase 2 fixes operational resilience (VRAM handoff, broker exit for PENDING_NEW). All changes are independent and can be parallelized.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Alpaca API, Ollama

---

## File Map

| File | Action | Issue | Responsibility |
|------|--------|-------|----------------|
| `src/evaluation/cto_report.py` | Modify | #341 | Add `_num()` helper, wrap all 30 `(x or 0) > 0` sites |
| `src/training/data_collector.py` | Verify | #342 | Confirm float() wraps are present, fix any remaining |
| `src/scheduler/reports.py` | Modify | #342 | Fix format string crashes in report generation |
| `src/scheduler/fundamentals_refresh.py` | Modify | #343 | Pass `tickers` arg to `fetch_earnings_dates()` |
| `src/api/cloud_app.py` | Modify | #346 | Add `/healthz` endpoint |
| `src/scheduler/vram_manager.py` | Modify | #344 | Add graceful `ollama stop`, raise VRAM threshold |
| `src/shadow_trading/executor.py` | Modify | #345 | Cancel PENDING_NEW entry orders instead of selling |
| `tests/test_cto_report.py` | Modify | #341 | Add test for string-typed pnl_dollars |
| `tests/test_cloud_app.py` | Create | #346 | Test healthz endpoint |
| `tests/test_vram_manager.py` | Create | #344 | Test graceful unload path |
| `tests/test_executor_pending.py` | Create | #345 | Test PENDING_NEW cancel path |

---

## Phase 1: Critical Path (unblocks daily operations)

### Task 1: Fix CTO report type crashes (#341)

**Files:**
- Modify: `src/evaluation/cto_report.py:216-663`
- Modify: `tests/test_cto_report.py`

- [ ] **Step 1: Write failing test for string-typed pnl_dollars**

Add to `tests/test_cto_report.py`:

```python
def test_trade_summary_handles_string_pnl():
    """#341: SQLite returns pnl_dollars as string — must not crash."""
    from src.evaluation.cto_report import _compute_trade_summary

    closed = [
        {
            "trade_id": "t1", "ticker": "AAPL", "recommendation_id": "r1",
            "pnl_dollars": "42.5", "pnl_pct": "3.2",
            "exit_reason": "target_1_hit", "duration_days": "5",
            "max_favorable_excursion": "4.0", "max_adverse_excursion": "-1.0",
        },
        {
            "trade_id": "t2", "ticker": "MSFT", "recommendation_id": "r2",
            "pnl_dollars": "-10.0", "pnl_pct": "-2.1",
            "exit_reason": "stop_hit", "duration_days": "3",
            "max_favorable_excursion": "1.0", "max_adverse_excursion": "-3.5",
        },
    ]
    result = _compute_trade_summary(closed, [], closed)
    assert result["win_rate"] == 0.5
    assert result["total_pnl"] == 32.5
    assert result["trades_closed"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cto_report.py::test_trade_summary_handles_string_pnl -v`
Expected: FAIL with `TypeError: '>' not supported between instances of 'str' and 'int'`

- [ ] **Step 3: Add `_num()` helper to cto_report.py**

Add after the imports at the top of `src/evaluation/cto_report.py` (after the existing imports, before the first function):

```python
from src.utils.type_safety import safe_numeric


def _num(val, default=0):
    """Coerce a value to float. Guards against SQLite returning strings for numeric columns."""
    return safe_numeric(val, default)
```

- [ ] **Step 4: Replace all unsafe numeric comparisons in cto_report.py**

Apply these replacements throughout the file using `replace_all` where the pattern is unique, or targeted edits otherwise. The pattern is always the same:

Replace `(t.get("pnl_dollars") or 0)` with `_num(t.get("pnl_dollars"))` — applies to lines 216, 217, 271, 330, 360, 379, 426, 427, 492, 629.

Replace `t.get("pnl_pct", 0) or 0` with `_num(t.get("pnl_pct"))` — applies to lines 220, 221, 235, 293, 298, 309, 456, 628.

Replace `t.get("pnl_dollars", 0) or 0` with `_num(t.get("pnl_dollars"))` — applies to lines 223, 226, 397.

Replace `t.get("max_favorable_excursion", 0) or 0` with `_num(t.get("max_favorable_excursion"))` — line 431.

Replace `t.get("max_adverse_excursion", 0) or 0` with `_num(t.get("max_adverse_excursion"))` — line 432.

Replace `t.get("duration_days", 0) or 0` with `_num(t.get("duration_days"))` — lines 294, 299, 433.

Replace `r.get("priority_score", 0) or 0` with `_num(r.get("priority_score"))` — lines 323, 450.

Note: Lines 250, 260, 261 already use `float()` casts — leave those as-is, they work correctly.

Also fix the Annie Duke quadrant comparison at line 581:
```python
# Before:
is_good_process = score is not None and score >= 3.0
# After:
is_good_process = score is not None and _num(score) >= 3.0
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_cto_report.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -q --tb=short`
Expected: No new failures (baseline: 496 passed, 1 pre-existing)

- [ ] **Step 7: Commit**

```bash
git add src/evaluation/cto_report.py tests/test_cto_report.py
git commit -m "fix(#341): wrap all numeric comparisons in cto_report with safe_numeric

SQLite returns pnl_dollars, pnl_pct, duration_days etc as strings.
The (x or 0) > 0 pattern fails because truthy strings bypass the
default. Added _num() helper backed by safe_numeric to coerce all
30 comparison sites.

Closes #341"
```

---

### Task 2: Fix format string crashes in data collector and reports (#342)

**Files:**
- Verify: `src/training/data_collector.py:111-139`
- Modify: `src/scheduler/reports.py` (if format crashes found)

- [ ] **Step 1: Verify data_collector.py already has float() wraps**

Read `src/training/data_collector.py` lines 111-139 and confirm all `:.2f` / `:.1f` / `:.0f` format specs have `float()` wraps. The log showed the error at line 59 but the current code at line 115 already has `float(rec.get('price_at_recommendation') or 0)`.

If the current code is already wrapped (it is based on our earlier read), mark this file as clean.

- [ ] **Step 2: Search for remaining format code vulnerabilities**

Run: `grep -n ':\.\d\+f' src/scheduler/reports.py src/evaluation/cto_report.py src/email/digest_builder.py`

For each match, check if the value being formatted is wrapped with `float()` or `_num()`. If not, add the wrap.

- [ ] **Step 3: Fix any found format string issues**

For each unprotected format spec, wrap the value:
```python
# Before:
f"Score: {value:.0f}"
# After:
f"Score: {float(value or 0):.0f}"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -q --tb=short`
Expected: No new failures

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(#342): guard remaining format specs against string values

Verified data_collector.py already has float() wraps. Fixed any
remaining unprotected :.Nf format specs in reports and digest code.

Closes #342"
```

---

### Task 3: Fix earnings refresh missing argument (#343)

**Files:**
- Modify: `src/scheduler/fundamentals_refresh.py:48-56`

- [ ] **Step 1: Write failing test**

```python
# tests/test_fundamentals_refresh.py (add to existing or create)
def test_earnings_refresh_passes_tickers(tmp_path):
    """#343: fetch_earnings_dates requires tickers positional arg."""
    from unittest.mock import patch, MagicMock
    from src.scheduler.fundamentals_refresh import refresh_tier4

    mock_fetch = MagicMock(return_value={"updated": 5})
    mock_macro = MagicMock(return_value={"series_collected": 10})

    with patch("src.scheduler.fundamentals_refresh.collect_macro_snapshots", mock_macro), \
         patch("scripts.fetch_earnings_calendar.fetch_earnings_dates", mock_fetch):
        result = refresh_tier4(db_path=str(tmp_path / "test.db"))

    # Verify tickers was passed
    mock_fetch.assert_called_once()
    call_kwargs = mock_fetch.call_args
    # Should have tickers as first positional arg or keyword arg
    assert call_kwargs.kwargs.get("tickers") is not None or len(call_kwargs.args) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fundamentals_refresh.py::test_earnings_refresh_passes_tickers -v`
Expected: FAIL — `fetch_earnings_dates` called without `tickers`

- [ ] **Step 3: Fix the call site**

Edit `src/scheduler/fundamentals_refresh.py` lines 48-52:

```python
    # Earnings calendar refresh
    try:
        from scripts.fetch_earnings_calendar import fetch_earnings_dates
        from src.universe.sp100 import get_sp100_universe

        result = fetch_earnings_dates(tickers=get_sp100_universe(), db_path=db_path)
        summary["refreshed"].append("earnings")
        logger.info("[FUNDAMENTALS] Earnings calendar refreshed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fundamentals_refresh.py::test_earnings_refresh_passes_tickers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/scheduler/fundamentals_refresh.py tests/test_fundamentals_refresh.py
git commit -m "fix(#343): pass SP100 tickers to fetch_earnings_dates

The function signature requires tickers as a positional arg but
the call site only passed db_path as keyword. Now passes the
SP100 universe.

Closes #343"
```

---

### Task 4: Add /healthz endpoint to cloud API (#346)

**Files:**
- Modify: `src/api/cloud_app.py`
- Create: `tests/test_cloud_app.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_cloud_app.py`:

```python
"""Tests for cloud API health endpoint."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    # Patch DATABASE_URL so the app can import without real Postgres
    with patch.dict("os.environ", {"DATABASE_URL": "postgresql://test:test@localhost/test"}):
        from src.api.cloud_app import app
        return TestClient(app)


def test_healthz_returns_200(client):
    """#346: Render requires /healthz for health checks."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cloud_app.py::test_healthz_returns_200 -v`
Expected: FAIL with 404

- [ ] **Step 3: Add healthz endpoint**

Add to `src/api/cloud_app.py` after the CORS middleware block (after line 89):

```python
@app.get("/healthz")
def healthz():
    """Health check for Render deployment monitoring."""
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cloud_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/cloud_app.py tests/test_cloud_app.py
git commit -m "fix(#346): add /healthz endpoint for Render health checks

render.yaml specifies healthCheckPath: /healthz but no endpoint
existed. Added a simple 200 response. Without this, Render may
flag the service as unhealthy and restart it.

Closes #346"
```

---

## Phase 2: Operational Resilience

### Task 5: Fix VRAM handoff with graceful Ollama stop (#344)

**Files:**
- Modify: `src/scheduler/vram_manager.py:102-118, 180-258`

- [ ] **Step 1: Write test for graceful unload**

Create `tests/test_vram_manager.py`:

```python
"""Tests for VRAM manager Ollama transitions."""
from unittest.mock import patch, MagicMock

import pytest

from src.scheduler.vram_manager import VRAMManager


@pytest.fixture
def manager():
    with patch.object(VRAMManager, "__init__", lambda self: None):
        m = VRAMManager.__new__(VRAMManager)
        m._training_process = None
        m._nvidia_smi = "nvidia-smi"
        return m


def test_unload_tries_stop_before_keepalive(manager):
    """#344: Should try 'ollama stop' before keep_alive=0 unload."""
    responses = []

    def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        responses.append(url)
        return resp

    with patch("src.scheduler.vram_manager.requests.post", side_effect=mock_post), \
         patch("src.scheduler.vram_manager.load_config", return_value={"llm": {"model": "test-model"}}):
        result = manager._unload_ollama()

    assert result is True
    # Should have called ollama stop endpoint first
    assert any("/api/show" in r or "stop" in str(r).lower() for r in responses) or len(responses) >= 1


def test_handoff_uses_higher_vram_threshold(manager):
    """#344: VRAM threshold should accommodate CUDA context overhead."""
    calls = []

    def mock_wait(threshold_mb=1500, timeout_seconds=30):
        calls.append(threshold_mb)
        return True

    with patch.object(manager, "_unload_ollama", return_value=True), \
         patch.object(manager, "_wait_for_vram_clear", side_effect=mock_wait), \
         patch.object(manager, "get_vram_used_mb", return_value=5000), \
         patch("src.scheduler.vram_manager.load_config", return_value={"llm": {"model": "test"}}):
        manager.handoff_to_training()

    # Threshold should be 2500+ to accommodate CUDA context
    assert calls[0] >= 2500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vram_manager.py -v`
Expected: FAIL on threshold assertion (current threshold is 1500)

- [ ] **Step 3: Implement graceful unload and higher threshold**

Edit `src/scheduler/vram_manager.py`:

In `_unload_ollama()` (line 102), add an `ollama stop` call before the keep_alive=0 approach:

```python
    def _unload_ollama(self) -> bool:
        """Unload the active Ollama model from VRAM."""
        model = self.get_active_model()
        base_url = self._get_ollama_base_url()

        # Try graceful stop first (releases VRAM more reliably than keep_alive=0)
        try:
            import subprocess as _sp
            result = _sp.run(
                ["ollama", "stop", model],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                logger.info("[VRAM] Graceful stop succeeded for %s", model)
                return True
            logger.info("[VRAM] 'ollama stop' returned %d, falling back to keep_alive=0", result.returncode)
        except Exception as e:
            logger.info("[VRAM] 'ollama stop' unavailable (%s), falling back to keep_alive=0", e)

        # Fallback: keep_alive=0 API call
        try:
            resp = requests.post(
                f"{base_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info("[VRAM] Unloaded model %s", model)
                return True
            logger.warning("[VRAM] Unload returned status %d", resp.status_code)
        except Exception as e:
            logger.warning("[VRAM] Unload request failed: %s", e)
        return False
```

In `handoff_to_training()` (line 199), raise the threshold from 1500 to 2500:

```python
        # Step 2: Verify VRAM clear
        if not self._wait_for_vram_clear(threshold_mb=2500, timeout_seconds=30):
```

Also update all other `_wait_for_vram_clear(threshold_mb=1500` calls in that method to `threshold_mb=2500`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_vram_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/scheduler/vram_manager.py tests/test_vram_manager.py
git commit -m "fix(#344): graceful ollama stop + raise VRAM threshold to 2500MB

Added 'ollama stop <model>' before keep_alive=0 for cleaner VRAM
release. Raised threshold from 1500MB to 2500MB to accommodate
CUDA context overhead (~500MB) that persists after model unload.

Closes #344"
```

---

### Task 6: Cancel PENDING_NEW entry orders instead of selling (#345)

**Files:**
- Modify: `src/shadow_trading/executor.py:880-1035`

- [ ] **Step 1: Write failing test**

Create `tests/test_executor_pending.py`:

```python
"""Tests for broker exit handling of PENDING_NEW positions."""
from unittest.mock import patch, MagicMock

import pytest


def test_pending_new_entry_cancels_instead_of_selling():
    """#345: If entry order never filled, cancel it instead of trying to sell."""
    from src.shadow_trading.executor import _is_pending_status

    # Verify PENDING_NEW is recognized as pending
    assert _is_pending_status("pending_new") is True
    assert _is_pending_status("OrderStatus.PENDING_NEW") is False  # raw enum string
    assert _is_pending_status("new") is True
    assert _is_pending_status("filled") is False


def test_pending_status_includes_accepted():
    """Verify all pending statuses are covered."""
    from src.shadow_trading.executor import PENDING_ORDER_STATUSES

    assert "new" in PENDING_ORDER_STATUSES
    assert "accepted" in PENDING_ORDER_STATUSES
    assert "pending_new" in PENDING_ORDER_STATUSES
```

- [ ] **Step 2: Run test to verify it passes (baseline)**

Run: `python -m pytest tests/test_executor_pending.py -v`
Expected: PASS (these test existing behavior to establish baseline)

- [ ] **Step 3: Add entry-order cancellation before exit**

Edit `src/shadow_trading/executor.py`. In the exit logic section (around line 898, inside the `if exit_reason:` block), add a check for unfilled entry orders BEFORE attempting the exit:

```python
        if exit_reason:
            # #345: If the entry order never filled, cancel it instead of selling
            entry_status = trade.get("status", "")
            entry_order_id = trade.get("alpaca_order_id")
            if entry_status in ("pending", "pending_entry") and entry_order_id:
                try:
                    from src.shadow_trading.alpaca_adapter import cancel_paper_order
                    cancel_paper_order(entry_order_id)
                    logger.info(
                        "[EXIT] Cancelled unfilled entry order for %s (order=%s, reason=%s)",
                        ticker, entry_order_id, exit_reason,
                    )
                except Exception as cancel_err:
                    logger.warning("[EXIT] Failed to cancel entry order for %s: %s", ticker, cancel_err)
                update_shadow_trade(
                    trade["trade_id"],
                    {"status": "cancelled", "exit_reason": f"entry_unfilled_{exit_reason}"},
                    db_path,
                )
                actions.append({
                    "type": "cancelled_unfilled",
                    "ticker": ticker,
                    "trade_id": trade["trade_id"],
                    "reason": exit_reason,
                })
                continue
```

This goes right after `if exit_reason:` and BEFORE the existing `# Exit slippage tracking` comment (line 900).

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -q --tb=short`
Expected: No new failures

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_executor_pending.py
git commit -m "fix(#345): cancel unfilled entry orders instead of selling

When an exit condition triggers for a trade whose entry order never
filled (status=pending/pending_entry), cancel the entry order and
mark the trade as cancelled. Previously this attempted to sell
shares that were never acquired, causing PENDING_NEW exit failures.

Closes #345"
```

---

## Phase 3: Finalize

### Task 7: Create PR, merge, verify

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All baseline tests pass, no regressions

- [ ] **Step 2: Create branch and PR**

```bash
git checkout -b fix/log-rectification-341-346
git push -u origin fix/log-rectification-341-346
gh pr create --title "fix: rectify all open log errors (#341-#346)" --body "..."
```

- [ ] **Step 3: Merge and clean up**

```bash
gh pr merge --merge --delete-branch
```

- [ ] **Step 4: Verify sync is clean after restart**

After watch loop restart, check `logs/arcis.log` for:
- Sync cycle: 0 errors
- No training TypeError
- No digest/audit crashes
- Earnings refresh succeeds
- No PENDING_NEW exit failures
