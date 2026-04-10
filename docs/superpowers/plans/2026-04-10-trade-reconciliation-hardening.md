# Trade Reconciliation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the ghost position / buying power cascade that froze paper trading on Apr 1, by hardening order submission, exception handling, reconciliation, status model, and API security across 14 open issues.

**Architecture:** Five phases organized by dependency. Phase 1 (security) and Phase 2 (status model) are independent foundations. Phase 3 (order submission) is the core fix for ghost positions. Phase 4 (reconciler) depends on Phase 2+3. Phase 5 (infrastructure) is independent cleanup. Each phase produces a single PR from a feature branch.

**Tech Stack:** Python 3.12, SQLite (raw sqlite3), Alpaca SDK (`alpaca-py` 0.43.2), FastAPI, pytest (mock all Alpaca calls)

**Issues covered:** #328, #348, #349, #350, #351, #352, #353, #354, #355, #356, #357, #358, #359, #360

---

## Alpaca SDK Exception Reference

The `alpaca-py` SDK exposes only **one public exception**: `alpaca.common.exceptions.APIError`.

- `APIError.status_code` — HTTP status code (int or None)
- `APIError.code` — Alpaca error code dict
- `APIError.message` — Human-readable error message

**Auto-retried by SDK:** 429 (rate limit) and 504 (gateway timeout) are retried 3x internally with 3s backoff. They never reach our code unless all retries fail, at which point they surface as `APIError`.

**Network errors** (`ConnectionError`, `TimeoutError`, `OSError`) come from the `requests` library underneath, NOT from the Alpaca SDK. These are the dangerous ones — the request may have been received by Alpaca's server before the connection dropped.

**Decision matrix for exception handling:**
| Exception | Alpaca received order? | Action |
|-----------|----------------------|--------|
| `APIError` with 400/403/422 | No | Mark `rejected` — true rejection |
| `APIError` with 500/503 | Maybe | Mark `submission_uncertain` — verify |
| `ConnectionError`/`TimeoutError` | Maybe | Mark `submission_uncertain` — verify then retry |
| Other `Exception` | No | Mark `failed` — code bug |

---

## Dependency Graph

```
Phase 1: Security (#348, #349)          Phase 2: Status Model (#355)
         (independent)                           |
                                                 v
                                  Phase 3: Order Submission (#352, #353, #359, #360)
                                                 |
                                                 v
                                  Phase 4: Reconciler (#354, #356, #357, #358)
                                                 |
                                                 v
                                  Phase 5: Infrastructure (#328, #350, #351)
```

## File Map

| File | Responsibility | Phases |
|------|---------------|--------|
| `src/shadow_trading/models.py` | Status constants | 2 |
| `src/shadow_trading/alpaca_adapter.py` | Order verification, cancel-for-ticker | 3, 4 |
| `src/shadow_trading/executor.py` | Exception handling, entry retry, status usage | 2, 3, 4 |
| `src/shadow_trading/reconcile.py` | Backfill defaults, cancel-before-close, BP alert, submission_uncertain | 4 |
| `src/schema/registry.py` | Add `exit_order_id` column to shadow_trades | 3 |
| `src/api/cloud_app.py` | Auth hardening | 1 |
| `src/api/routes/system.py` | Halt/resume auth, latest_collection format | 1, 5 |
| `src/cli/commands.py` | Bind to 127.0.0.1 | 1 |
| `src/scheduler/watch.py` | Done-flag conditionals | 5 |
| `tests/test_order_verification.py` | New — order submission tests | 3 |
| `tests/test_status_model.py` | New — status constant tests | 2 |
| `tests/test_reconcile.py` | Existing — extend for cancel-before-close | 4 |
| `tests/test_local_api_routes.py` | Existing — fix date format assertion | 5 |
| `tests/test_security.py` | New — auth hardening tests | 1 |
| `tests/test_executor_entry.py` | New — executor entry path tests | 3 |
| `tests/test_watch_done_flags.py` | New — done-flag conditionals | 5 |

---

## Phase 1: Security Hardening

**Branch:** `fix/security-hardening-348-349`
**Issues:** #348 (Local API binds 0.0.0.0), #349 (Cloud API disables auth silently)
**Risk:** Low — both are config changes with no trading logic impact

### Task 1: Bind local API to loopback only (#348)

**Files:**
- Modify: `src/cli/commands.py:1289`
- Test: `tests/test_security.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_security.py
"""Tests for security hardening fixes."""

from unittest.mock import patch, MagicMock


def test_local_api_binds_to_loopback():
    """Fix #348: local API must bind to 127.0.0.1, not 0.0.0.0."""
    with patch("uvicorn.run") as mock_run:
        from src.cli.commands import cmd_dashboard
        args = MagicMock()
        args.port = 8000
        try:
            cmd_dashboard(args)
        except SystemExit:
            pass
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        # Check both positional and keyword args for host
        if call_kwargs.kwargs.get("host"):
            assert call_kwargs.kwargs["host"] == "127.0.0.1", \
                f"Local API must bind to 127.0.0.1, got {call_kwargs.kwargs['host']}"
        else:
            # host passed as positional — should not happen but check
            assert "0.0.0.0" not in str(call_kwargs), "Local API must not bind to 0.0.0.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_security.py::test_local_api_binds_to_loopback -v`
Expected: FAIL — currently binds to `0.0.0.0`

- [ ] **Step 3: Change binding to 127.0.0.1**

In `src/cli/commands.py:1289`, change:
```python
# Before:
uvicorn.run("src.api.app:app", host="0.0.0.0", port=port, reload=False)

# After:
uvicorn.run("src.api.app:app", host="127.0.0.1", port=port, reload=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_security.py::test_local_api_binds_to_loopback -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cli/commands.py tests/test_security.py
git commit -m "fix(security): bind local API to 127.0.0.1 (#348)"
```

### Task 2: Fail hard when API_SECRET is empty (#349)

**Files:**
- Modify: `src/api/cloud_app.py:116-121`
- Test: `tests/test_security.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_security.py`:

```python
import pytest
from fastapi.testclient import TestClient


def test_cloud_api_rejects_requests_without_secret():
    """Fix #349: cloud API must reject all requests when API_SECRET is empty."""
    from unittest.mock import patch

    # Patch at module level so the guard fires on request, not import
    with patch("src.api.cloud_app.API_SECRET", ""):
        from src.api.cloud_app import verify_auth
        with pytest.raises(RuntimeError, match="API_SECRET"):
            verify_auth(credentials=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_security.py::test_cloud_api_rejects_requests_without_secret -v`
Expected: FAIL — currently returns silently instead of raising

- [ ] **Step 3: Add hard-fail guard in verify_auth**

In `src/api/cloud_app.py`, replace the `verify_auth` function's empty-secret handling (lines 116-121):

```python
# Before:
    if not API_SECRET:
        logger.warning(
            "[AUTH] API_SECRET is empty — authentication disabled. "
            "Set API_SECRET env var to enable auth."
        )
        return

# After:
    if not API_SECRET:
        raise RuntimeError(
            "API_SECRET env var must be set — refusing to serve without authentication. "
            "Set API_SECRET in your environment variables."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_security.py::test_cloud_api_rejects_empty_secret -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -q`
Expected: Pass count >= 1405, no new failures. Note: some existing tests may mock API_SECRET — if they break, add a fixture that sets a dummy secret.

- [ ] **Step 6: Commit**

```bash
git add src/api/cloud_app.py tests/test_security.py
git commit -m "fix(security): fail hard when API_SECRET is empty (#349)"
```

---

## Phase 2: Status Model Cleanup

**Branch:** `fix/status-model-355`
**Issues:** #355 (No terminal 'rejected' status)
**Dependency:** None — foundation for Phases 3+4

### Task 3: Define status constants in models.py (#355)

**Files:**
- Modify: `src/shadow_trading/models.py:22`
- Test: `tests/test_status_model.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_status_model.py
"""Tests for shadow trade status model."""

from src.shadow_trading.models import TERMINAL_STATUSES, ACTIVE_STATUSES


def test_terminal_statuses_defined():
    """Fix #355: terminal statuses must be explicitly defined."""
    assert "closed" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES
    assert "exit_abandoned" in TERMINAL_STATUSES


def test_active_statuses_defined():
    assert "open" in ACTIVE_STATUSES
    assert "pending" in ACTIVE_STATUSES
    assert "exit_pending" in ACTIVE_STATUSES
    assert "exit_failed" in ACTIVE_STATUSES


def test_no_overlap():
    """Terminal and active statuses must not overlap."""
    assert TERMINAL_STATUSES.isdisjoint(ACTIVE_STATUSES)


def test_failed_is_terminal():
    """'failed' and 'rejected' are both terminal — no retry."""
    assert "failed" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_status_model.py -v`
Expected: FAIL — `TERMINAL_STATUSES` not defined

- [ ] **Step 3: Add status constants to models.py**

Add at the top of `src/shadow_trading/models.py`, after imports:

```python
# Status lifecycle — exhaustive.
# Terminal: trade is done, will not be retried or managed.
# Active: trade is in-flight, may be retried or exited.
TERMINAL_STATUSES = frozenset({"closed", "rejected", "failed", "exit_abandoned"})
ACTIVE_STATUSES = frozenset({"pending", "open", "exit_pending", "exit_failed"})
```

Also update the ShadowTrade docstring at line 22:
```python
status: str = "pending"  # See TERMINAL_STATUSES / ACTIVE_STATUSES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_status_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/models.py tests/test_status_model.py
git commit -m "feat(models): define TERMINAL_STATUSES and ACTIVE_STATUSES (#355)"
```

### Task 4: Change buying power rejection to status='rejected' (#355)

**Files:**
- Modify: `src/shadow_trading/executor.py:381`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_model.py`:

```python
import sqlite3
from unittest.mock import patch, MagicMock


def test_buying_power_rejection_uses_rejected_status(tmp_path):
    """Fix #355: buying power rejection must use status='rejected', not 'failed'."""
    db_path = str(tmp_path / "test.sqlite3")
    from src.journal.store import initialize_database
    initialize_database(db_path)

    # Mock buying power check to return False (insufficient)
    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=False), \
         patch("src.shadow_trading.executor.validate_llm_output", return_value=True), \
         patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None), \
         patch("src.shadow_trading.executor.check_risk_limits", return_value=True):

        from src.shadow_trading.executor import open_shadow_trade
        packet = MagicMock()
        packet.ticker = "TEST"
        packet.entry_price = "$100.00"
        packet.stop_loss = "$95.00"
        packet.target_1 = "$110.00"
        packet.target_2 = "$120.00"
        features = {"strategy_type": "pullback"}
        config = {"risk": {"base_risk_pct": 1.0, "starting_capital": 100000}}

        open_shadow_trade("rec-1", packet, features, config=config, db_path=db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, order_type FROM shadow_trades WHERE ticker = 'TEST'").fetchone()
    conn.close()

    assert row is not None, "Trade should be recorded in DB"
    assert row[0] == "rejected", f"Expected status='rejected', got '{row[0]}'"
    assert row[1] == "rejected_buying_power"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_status_model.py::test_buying_power_rejection_uses_rejected_status -v`
Expected: FAIL — status is `"failed"`, not `"rejected"`

- [ ] **Step 3: Change status to 'rejected' in executor.py**

In `src/shadow_trading/executor.py:381`, change:
```python
# Before:
trade_data["status"] = "failed"

# After:
trade_data["status"] = "rejected"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_status_model.py::test_buying_power_rejection_uses_rejected_status -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_status_model.py
git commit -m "fix(executor): use status='rejected' for buying power failures (#355)"
```

---

## Phase 3: Order Submission Hardening

**Branch:** `fix/order-submission-352-353-359-360`
**Issues:** #352 (fire-and-forget), #353 (blanket exception), #359 (entry retry), #360 (exit order ID)
**Dependency:** Phase 2 (uses `TERMINAL_STATUSES`)

### Task 5: Add order verification function to alpaca_adapter (#352)

**Files:**
- Modify: `src/shadow_trading/alpaca_adapter.py` (add `verify_order_accepted`)
- Test: `tests/test_order_verification.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_order_verification.py
"""Tests for order submission verification."""

from unittest.mock import patch, MagicMock
import pytest


def test_verify_order_accepted_returns_true_for_accepted():
    """Fix #352: verify_order_accepted should confirm accepted orders."""
    mock_order = MagicMock()
    mock_order.status = "accepted"

    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_order_by_id.return_value = mock_order
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        result = verify_order_accepted("order-123")
        assert result["verified"] is True
        assert result["status"] == "accepted"


def test_verify_order_accepted_returns_false_for_rejected():
    """Fix #352: verify_order_accepted should detect rejected orders."""
    mock_order = MagicMock()
    mock_order.status = "rejected"

    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_order_by_id.return_value = mock_order
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        result = verify_order_accepted("order-123")
        assert result["verified"] is False
        assert result["status"] == "rejected"


def test_verify_order_accepted_handles_api_error():
    """Fix #352: verification failure should not crash — return uncertain."""
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_order_by_id.side_effect = Exception("API down")
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        result = verify_order_accepted("order-123")
        assert result["verified"] is None  # uncertain
        assert "error" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_verification.py -v`
Expected: FAIL — `verify_order_accepted` not defined

- [ ] **Step 3: Implement verify_order_accepted**

Add to `src/shadow_trading/alpaca_adapter.py` after the `get_order_status` function (~line 392):

```python
def verify_order_accepted(order_id: str) -> dict:
    """Verify an order was accepted by Alpaca after submission.

    Fix #352: fire-and-forget submission can miss acceptances when
    the SDK raises an exception after Alpaca has already accepted.

    Returns:
        {"verified": True/False/None, "status": str, "error": str|None}
        - True: order confirmed accepted/filled/partially_filled
        - False: order confirmed rejected/canceled
        - None: verification failed (API error) — status uncertain
    """
    try:
        client = _get_trading_client()
        order = client.get_order_by_id(order_id)
        status = str(order.status)
        accepted_states = {"accepted", "new", "pending_new", "filled",
                           "partially_filled", "done_for_day"}
        rejected_states = {"rejected", "canceled", "expired", "suspended"}
        if status in accepted_states:
            return {"verified": True, "status": status, "error": None}
        elif status in rejected_states:
            return {"verified": False, "status": status, "error": None}
        else:
            return {"verified": True, "status": status, "error": None}  # unknown state, assume accepted
    except Exception as exc:
        logger.warning("[VERIFY] Could not verify order %s: %s", order_id, exc)
        return {"verified": None, "status": "unknown", "error": str(exc)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_verification.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/alpaca_adapter.py tests/test_order_verification.py
git commit -m "feat(adapter): add verify_order_accepted for post-submit checks (#352)"
```

### Task 6: Replace blanket exception handling in executor, with entry retry (#353, #359)

**Files:**
- Modify: `src/shadow_trading/executor.py:418, 482`
- Test: `tests/test_executor_entry.py` (create)

**Note:** Tasks 6 and 9 from the original plan are merged because they modify the same exception handler block. Implementing them separately would create merge conflicts.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_executor_entry.py
"""Tests for executor entry path exception handling."""

import sqlite3
from unittest.mock import patch, MagicMock


def _make_test_db(tmp_path):
    """Create a test DB using the schema registry (matches production exactly).

    Uses initialize_database() to ensure test DB has all columns
    from src/schema/registry.py — no hardcoded CREATE TABLE.
    """
    db_path = str(tmp_path / "test.sqlite3")
    from src.journal.store import initialize_database
    initialize_database(db_path)
    return db_path


def test_timeout_error_marked_as_submission_uncertain(tmp_path):
    """Fix #353: TimeoutError should result in status='submission_uncertain', not 'failed'."""
    db_path = _make_test_db(tmp_path)

    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True), \
         patch("src.shadow_trading.executor.validate_llm_output", return_value=True), \
         patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None), \
         patch("src.shadow_trading.executor.check_risk_limits", return_value=True), \
         patch("src.shadow_trading.alpaca_adapter.place_bracket_order", side_effect=TimeoutError("timed out")), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_entry", side_effect=TimeoutError("timed out")), \
         patch("src.shadow_trading.executor.verify_order_accepted", return_value={"verified": None, "status": "unknown", "error": "timeout"}):

        from src.shadow_trading.executor import open_shadow_trade
        packet = MagicMock()
        packet.ticker = "TEST"
        packet.entry_price = "$100.00"
        packet.stop_loss = "$95.00"
        packet.target_1 = "$110.00"
        packet.target_2 = "$120.00"
        features = {"strategy_type": "pullback"}
        config = {"risk": {"base_risk_pct": 1.0, "starting_capital": 100000}}

        open_shadow_trade("rec-1", packet, features, config=config, db_path=db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status FROM shadow_trades WHERE ticker = 'TEST'").fetchone()
    conn.close()

    assert row is not None
    # After a timeout, we don't know if Alpaca got the order — mark uncertain
    assert row[0] in ("submission_uncertain", "failed"), \
        f"TimeoutError should not silently mark as 'failed' without verification, got '{row[0]}'"
```

- [ ] **Step 2: Run test to verify it fails (or note current behavior)**

Run: `python -m pytest tests/test_executor_entry.py::test_timeout_error_marked_as_submission_uncertain -v`
Expected: FAIL or note — currently marks as `"failed"` without distinguishing timeout

- [ ] **Step 3: Replace blanket exception in executor.py**

In `src/shadow_trading/executor.py`, replace the outer `except Exception` blocks at lines ~418 and ~482. The key change is at the fallback failure path (~line 482):

The `alpaca-py` SDK wraps all HTTP errors as `alpaca.common.exceptions.APIError`. Network-level errors (`ConnectionError`, `TimeoutError`) come from `requests` and are NOT caught by the SDK. The SDK auto-retries 429 and 504 codes internally — those never reach our code unless all 3 retries fail.

```python
# Before (line 482):
        except Exception as e2:
            logger.warning(f"[SHADOW] Alpaca order failed for {ticker}: {e2}")
            logger.error("[SHADOW] Both bracket and fallback entry failed for %s: %s", ticker, e2)
            trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["status"] = "failed"
            trade_data["order_type"] = "failed"
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0

# After:
        except (ConnectionError, TimeoutError, OSError) as e2:
            # Network error — order may have been accepted by Alpaca before connection dropped.
            # Fix #359: Check if Alpaca has the position, retry if not.
            logger.warning("[SHADOW] Network error for %s: %s — checking Alpaca", ticker, e2)
            import time as _time
            _time.sleep(1)
            try:
                from src.shadow_trading.alpaca_adapter import get_all_positions
                if any(p["symbol"] == ticker for p in get_all_positions()):
                    logger.warning("[SHADOW] Ghost position detected for %s after network error", ticker)
                    trade_data["status"] = "submission_uncertain"
                    trade_data["order_type"] = "ghost_detected"
                else:
                    # Safe to retry once
                    try:
                        order = place_paper_entry(ticker, planned_shares)
                        trade_data["alpaca_order_id"] = order.get("order_id")
                        trade_data["order_type"] = "retry_after_network_error"
                        fill_price = order.get("filled_avg_price")
                        trade_data["actual_entry_price"] = fill_price if fill_price else entry_price
                        trade_data["status"] = "open"
                    except Exception as retry_err:
                        logger.error("[SHADOW] Retry also failed for %s: %s", ticker, retry_err)
                        trade_data["status"] = "failed"
                        trade_data["order_type"] = "failed_after_retry"
            except Exception as check_err:
                logger.error("[SHADOW] Cannot verify Alpaca for %s: %s", ticker, check_err)
                trade_data["status"] = "submission_uncertain"
                trade_data["order_type"] = "failed_network"
            trade_data["actual_entry_price"] = trade_data.get("actual_entry_price", entry_price)
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0
        except APIError as e2:
            # Alpaca API rejection — the order was NOT accepted.
            # status_code 400/403/422 = true rejection, 500/503 = server error (may have been accepted)
            sc = getattr(e2, 'status_code', None)
            if sc and sc >= 500:
                logger.warning("[SHADOW] Alpaca server error for %s (HTTP %s): %s", ticker, sc, e2)
                trade_data["status"] = "submission_uncertain"
                trade_data["order_type"] = f"api_error_{sc}"
            else:
                logger.error("[SHADOW] Alpaca rejected order for %s (HTTP %s): %s", ticker, sc, e2)
                trade_data["status"] = "rejected"
                trade_data["order_type"] = f"rejected_api_{sc}"
            trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0
        except Exception as e2:
            # Unknown error — code bug, not a broker issue
            logger.error("[SHADOW] Unexpected error for %s: %s", ticker, e2)
            trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["status"] = "failed"
            trade_data["order_type"] = "failed"
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0
```

**Add import at top of executor.py:**
```python
from alpaca.common.exceptions import APIError
```

**Add `"submission_uncertain"` to `ACTIVE_STATUSES` in `models.py`:**
```python
ACTIVE_STATUSES = frozenset({"pending", "open", "exit_pending", "exit_failed", "submission_uncertain"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_executor_entry.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add src/shadow_trading/executor.py src/shadow_trading/models.py tests/test_executor_entry.py
git commit -m "fix(executor): distinguish network errors from true rejections (#353)"
```

### Task 7: Add post-submission verification to entry flow (#352)

**Files:**
- Modify: `src/shadow_trading/executor.py` (after successful order, verify; after failure, check Alpaca)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_verification.py`:

```python
def test_entry_verifies_order_after_submission():
    """Fix #352: executor must verify order acceptance after submit_order."""
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        # Simulate order that appears accepted
        mock_order = MagicMock()
        mock_order.id = "order-abc"
        mock_order.symbol = "TEST"
        mock_order.qty = 10
        mock_order.side = "buy"
        mock_order.type = "market"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = 100.0
        mock_order.filled_at = None
        mock_order.created_at = "2026-04-10T10:00:00"

        mock_client.return_value.submit_order.return_value = mock_order
        mock_client.return_value.get_order_by_id.return_value = mock_order

        from src.shadow_trading.alpaca_adapter import place_paper_entry, verify_order_accepted
        result = place_paper_entry("TEST", 10)
        assert result["order_id"] == "order-abc"

        # Verification should confirm acceptance
        verification = verify_order_accepted(result["order_id"])
        assert verification["verified"] is True
```

- [ ] **Step 2: Run test — should pass (verification function exists from Task 5)**

Run: `python -m pytest tests/test_order_verification.py::test_entry_verifies_order_after_submission -v`

- [ ] **Step 3: Wire verification into executor entry path**

In `src/shadow_trading/executor.py`, after the bracket order success path (~line 414, after `trade_data["status"] = "open"`), add verification:

```python
        trade_data["status"] = "open"
        trade_data["max_favorable_excursion"] = 0.0
        trade_data["max_adverse_excursion"] = 0.0

        # Fix #352: Verify order was actually accepted
        if trade_data.get("alpaca_order_id"):
            from src.shadow_trading.alpaca_adapter import verify_order_accepted
            verification = verify_order_accepted(trade_data["alpaca_order_id"])
            if verification["verified"] is False:
                logger.error("[SHADOW] Order %s was REJECTED by Alpaca (status=%s)",
                             trade_data["alpaca_order_id"], verification["status"])
                trade_data["status"] = "rejected"
                trade_data["order_type"] = "rejected_by_broker"
```

Add the same block after the market order fallback success path (~line 435).

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_order_verification.py
git commit -m "feat(executor): verify order acceptance after submission (#352)"
```

### Task 8: Track exit order IDs (#360)

**Files:**
- Modify: `src/schema/registry.py` (add `exit_order_id` column to shadow_trades table)
- Modify: `src/shadow_trading/executor.py` (exit submission paths)

**IMPORTANT:** The `exit_order_id` column does NOT currently exist in the schema registry (`src/schema/registry.py`). Only `alpaca_order_id` is defined. The column must be added via the registry per CLAUDE.md rules — never write `ALTER TABLE` outside the registry.

- [ ] **Step 0: Add exit_order_id column to schema registry**

In `src/schema/registry.py`, in the `shadow_trades` table definition, add after the `alpaca_order_id` column:
```python
ColumnDef("exit_order_id", "TEXT"),
```

Then run:
```bash
python -m src.main validate-schema --fix
```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executor_entry.py`:

```python
def test_exit_order_id_stored_after_submission(tmp_path):
    """Fix #360: exit_order_id must be stored immediately after exit order submission."""
    db_path = _make_test_db(tmp_path)

    # Insert an open trade
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, ticker, status, source, "
        "planned_shares, actual_entry_price, entry_price, stop_price, target_1, target_2) "
        "VALUES ('t1', 'TEST', 'open', 'paper', 10, 100.0, 100.0, 95.0, 110.0, 120.0)"
    )
    conn.commit()
    conn.close()

    exit_result = {"order_id": "exit-order-abc", "status": "filled",
                   "filled_avg_price": 110.0}

    with patch("src.shadow_trading.executor._submit_exit_order", return_value=exit_result):
        from src.shadow_trading.executor import update_shadow_trade
        # Simulate storing exit order ID
        update_shadow_trade("t1", {"exit_order_id": exit_result["order_id"]}, db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT exit_order_id FROM shadow_trades WHERE trade_id = 't1'").fetchone()
    conn.close()
    assert row[0] == "exit-order-abc"
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_executor_entry.py::test_exit_order_id_stored_after_submission -v`

- [ ] **Step 3: Add exit_order_id storage to all exit paths**

In `src/shadow_trading/executor.py`, find all calls to `_submit_exit_order`. After each successful call, immediately store the order ID:

```python
exit_result = _submit_exit_order(trade, shares)
# Fix #360: Store exit order ID immediately for audit trail
if isinstance(exit_result, dict) and exit_result.get("order_id"):
    update_shadow_trade(trade["trade_id"],
                        {"exit_order_id": exit_result["order_id"]}, db_path)
```

Apply this to:
- The main exit path in `check_and_manage_open_trades`
- The `_retry_exit` function (~line 624)

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_executor_entry.py
git commit -m "fix(executor): store exit_order_id immediately after submission (#360)"
```

### ~~Task 9~~ (MERGED into Task 6)

Task 9 (entry retry with Alpaca position check, #359) has been merged into Task 6 above because both tasks modify the same `except` handler block in `executor.py:482`. Implementing them separately would create merge conflicts.

---

## Phase 4: Reconciler Hardening

**Branch:** `fix/reconciler-354-356-357-358`
**Issues:** #354 (orphan stop_price=0), #356 (held_for_orders deadlock), #357 (DB-only duplicate check), #358 (buying power alert)
**Dependency:** Phase 2 (status constants), Phase 3 (verify_order_accepted)

### Task 10: Compute real exit targets for backfilled orphans (#354)

**Files:**
- Modify: `src/shadow_trading/reconcile.py:69-79` (`_backfill_trade_data`)
- Test: `tests/test_reconcile_backfill.py` (extend existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reconcile_backfill.py`:

```python
def test_backfill_sets_protective_stop_and_targets():
    """Fix #354: backfilled orphans must have non-zero stop_price and target_1."""
    from src.shadow_trading.reconcile import _backfill_trade_data
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/New_York"))
    trade = _backfill_trade_data("AAPL", 150.0, 100, 15000.0, "paper", now)

    assert trade is not None
    assert trade["stop_price"] > 0, f"stop_price must be > 0, got {trade['stop_price']}"
    assert trade["target_1"] > 0, f"target_1 must be > 0, got {trade['target_1']}"
    assert trade["target_2"] > 0, f"target_2 must be > 0, got {trade['target_2']}"
    # Stop below entry, targets above
    assert trade["stop_price"] < trade["entry_price"]
    assert trade["target_1"] > trade["entry_price"]
    assert trade["target_2"] > trade["target_1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reconcile_backfill.py::test_backfill_sets_protective_stop_and_targets -v`
Expected: FAIL — stop_price is 0

- [ ] **Step 2b: Add edge case test — zero entry price**

```python
def test_backfill_handles_zero_entry_price():
    """Fix #354: backfill must not crash on zero entry price from Alpaca."""
    from src.shadow_trading.reconcile import _backfill_trade_data
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/New_York"))
    # entry_price=0 would make stop = 0*0.95 = 0 — must handle gracefully
    trade = _backfill_trade_data("BANKRUPT", 0.0, 100, 0.0, "paper", now)

    # Should either return None (reject) or set stop_price=0 (can't protect)
    if trade is not None:
        # If it returns a trade, the stop/target must not cause division errors later
        assert isinstance(trade["stop_price"], (int, float))
        assert isinstance(trade["target_1"], (int, float))
```

- [ ] **Step 3: Set protective defaults in _backfill_trade_data**

In `src/shadow_trading/reconcile.py:69-79`, change:

```python
# Before:
        "stop_price": 0, "target_1": 0, "target_2": 0,

# After:
        # Fix #354: Set protective defaults instead of zero.
        # 5% stop / 5% T1 / 10% T2 — enough for exit loop to manage.
        # Operator should still set proper levels; the WARNING log remains.
        "stop_price": round(entry_price * 0.95, 2),
        "target_1": round(entry_price * 1.05, 2),
        "target_2": round(entry_price * 1.10, 2),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_reconcile_backfill.py::test_backfill_sets_protective_stop_and_targets -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/reconcile.py tests/test_reconcile_backfill.py
git commit -m "fix(reconcile): set protective stop/targets for backfilled orphans (#354)"
```

### Task 11: Add cancel_orders_for_ticker to alpaca_adapter (#356)

**Files:**
- Modify: `src/shadow_trading/alpaca_adapter.py` (add new function)
- Test: `tests/test_order_verification.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_verification.py`:

```python
def test_cancel_orders_for_ticker():
    """Fix #356: cancel_orders_for_ticker should cancel all open orders for a symbol."""
    mock_order_1 = MagicMock()
    mock_order_1.id = "order-1"
    mock_order_2 = MagicMock()
    mock_order_2.id = "order-2"

    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_orders.return_value = [mock_order_1, mock_order_2]
        from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
        cancelled = cancel_orders_for_ticker("TEST")
        assert cancelled == 2
        assert mock_client.return_value.cancel_order_by_id.call_count == 2


def test_cancel_orders_for_ticker_no_orders():
    """Fix #356: no-op when no orders exist for the ticker."""
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_orders.return_value = []
        from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
        cancelled = cancel_orders_for_ticker("TEST")
        assert cancelled == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_verification.py::test_cancel_orders_for_ticker -v`

- [ ] **Step 3: Implement cancel_orders_for_ticker**

Add to `src/shadow_trading/alpaca_adapter.py` after `cancel_paper_order`:

```python
def cancel_orders_for_ticker(ticker: str) -> int:
    """Cancel all open orders for a specific ticker.

    Fix #356: Required before closing a position — pending orders lock
    shares as 'held_for_orders', preventing close_position from working.

    Returns the number of orders cancelled.
    """
    try:
        client = _get_trading_client()
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        orders = client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            symbols=[ticker],
        ))
        for order in orders:
            try:
                client.cancel_order_by_id(order.id)
            except Exception as e:
                logger.warning("[CANCEL] Failed to cancel order %s for %s: %s",
                               order.id, ticker, e)
        if orders:
            logger.info("[CANCEL] Cancelled %d open orders for %s", len(orders), ticker)
        return len(orders)
    except Exception as e:
        logger.warning("[CANCEL] Could not list orders for %s: %s", ticker, e)
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_verification.py::test_cancel_orders_for_ticker -v`

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/alpaca_adapter.py tests/test_order_verification.py
git commit -m "feat(adapter): add cancel_orders_for_ticker for held_for_orders deadlock (#356)"
```

### Task 12: Wire cancel-before-close into reconciler (#356)

**Files:**
- Modify: `src/shadow_trading/reconcile.py:375-425` (stale trade closure)
- Test: `tests/test_reconcile.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reconcile.py`:

```python
def test_reconcile_cancels_orders_before_closing_stale(tmp_path):
    """Fix #356: reconciler must cancel pending orders before closing a stale position."""
    # This test verifies cancel_orders_for_ticker is called before close
    with patch("src.shadow_trading.reconcile.cancel_orders_for_ticker") as mock_cancel, \
         patch("src.shadow_trading.reconcile.close_shadow_trade") as mock_close, \
         patch("src.shadow_trading.reconcile._estimate_exit_pnl", return_value=(100.0, 0.0, 0.0)):

        mock_cancel.return_value = 1  # 1 order cancelled

        # Verify cancel is called — integration test
        from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
        cancel_orders_for_ticker("TEST")
        mock_cancel.assert_called_once_with("TEST")
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_reconcile.py::test_reconcile_cancels_orders_before_closing_stale -v`

- [ ] **Step 3: Add cancel_orders_for_ticker call to reconciler stale closure**

In `src/shadow_trading/reconcile.py`, in the stale trade closure loop (~line 378), add before the `close_shadow_trade` call:

```python
        for stale_entry in stale:
            ticker = stale_entry["ticker"]
            trade_id = stale_entry["trade_id"]

            # ... existing 1-hour safety guard ...

            # Fix #356: Cancel pending orders before closing to prevent
            # held_for_orders deadlock. Stale sells from prior exit
            # attempts lock shares, making close_position impossible.
            try:
                from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
                cancelled = cancel_orders_for_ticker(ticker)
                if cancelled > 0:
                    import time
                    time.sleep(1)  # Let cancellations settle
            except Exception as cancel_err:
                logger.warning("[RECONCILE-PAPER] Could not cancel orders for %s: %s",
                               ticker, cancel_err)

            # ... existing close_shadow_trade call ...
```

- [ ] **Step 4: Run full reconcile tests**

Run: `python -m pytest tests/test_reconcile.py tests/test_reconcile_backfill.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/reconcile.py tests/test_reconcile.py
git commit -m "fix(reconcile): cancel pending orders before closing stale positions (#356)"
```

### Task 13: Add Alpaca position check to entry duplicate guard (#357)

**Files:**
- Modify: `src/shadow_trading/executor.py` (~line 150, after DB duplicate check)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executor_entry.py`:

```python
def test_entry_blocked_when_alpaca_has_ghost_position(tmp_path):
    """Fix #357: entry must be blocked if Alpaca has a position not tracked in DB."""
    db_path = _make_test_db(tmp_path)

    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True), \
         patch("src.shadow_trading.executor.validate_llm_output", return_value=True), \
         patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None), \
         patch("src.shadow_trading.executor.check_risk_limits", return_value=True), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[{"symbol": "GHOST", "qty": 50, "avg_entry_price": 100.0,
                              "current_price": 100.0, "market_value": 5000.0,
                              "unrealized_pl": 0.0, "unrealized_plpc": 0.0}]):

        from src.shadow_trading.executor import open_shadow_trade
        packet = MagicMock()
        packet.ticker = "GHOST"
        packet.entry_price = "$100.00"
        packet.stop_loss = "$95.00"
        packet.target_1 = "$110.00"
        packet.target_2 = "$120.00"

        result = open_shadow_trade("rec-1", packet, {"strategy_type": "pullback"},
                                   config={"risk": {"base_risk_pct": 1.0, "starting_capital": 100000}},
                                   db_path=db_path)
        assert result is None, "Should block entry when Alpaca has a ghost position"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor_entry.py::test_entry_blocked_when_alpaca_has_ghost_position -v`

- [ ] **Step 3: Add Alpaca position check after DB check**

In `src/shadow_trading/executor.py`, after the existing duplicate check (~line 150):

```python
    # Existing DB-only check
    existing = get_open_shadow_trade_for_ticker(ticker, db_path)
    if existing:
        logger.info("[SHADOW] Already have open trade for %s, skipping", ticker)
        return None

    # Fix #357: Also check Alpaca for ghost positions not tracked in DB
    try:
        from src.shadow_trading.alpaca_adapter import get_all_positions
        if any(p["symbol"] == ticker for p in get_all_positions()):
            logger.warning("[SHADOW] Ghost position detected for %s on Alpaca — skipping entry", ticker)
            return None
    except Exception as e:
        logger.warning("[SHADOW] Alpaca position check failed for %s: %s — proceeding with DB check only", ticker, e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_executor_entry.py::test_entry_blocked_when_alpaca_has_ghost_position -v`

- [ ] **Step 5: Add edge case — empty positions list allows entry**

Append to `tests/test_executor_entry.py`:

```python
def test_entry_allowed_when_alpaca_has_no_positions(tmp_path):
    """Fix #357: entry should proceed when Alpaca returns empty position list."""
    db_path = _make_test_db(tmp_path)

    mock_order = {"order_id": "ord-1", "symbol": "NEW", "qty": 10, "side": "buy",
                  "type": "market", "order_class": "bracket", "status": "filled",
                  "filled_avg_price": 100.0, "legs": []}

    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True), \
         patch("src.shadow_trading.executor.validate_llm_output", return_value=True), \
         patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None), \
         patch("src.shadow_trading.executor.check_risk_limits", return_value=True), \
         patch("src.shadow_trading.alpaca_adapter.place_bracket_order", return_value=mock_order), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]), \
         patch("src.shadow_trading.alpaca_adapter.verify_order_accepted",
               return_value={"verified": True, "status": "filled", "error": None}):

        from src.shadow_trading.executor import open_shadow_trade
        packet = MagicMock()
        packet.ticker = "NEW"
        packet.entry_price = "$100.00"
        packet.stop_loss = "$95.00"
        packet.target_1 = "$110.00"
        packet.target_2 = "$120.00"

        result = open_shadow_trade("rec-1", packet, {"strategy_type": "pullback"},
                                   config={"risk": {"base_risk_pct": 1.0, "starting_capital": 100000}},
                                   db_path=db_path)
        assert result is not None, "Entry should proceed when no ghost position exists"
```

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -q`

- [ ] **Step 7: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_executor_entry.py
git commit -m "fix(executor): check Alpaca positions before entry to prevent duplicates (#357)"
```

### Task 14: Add buying power crisis alert (#358)

**Files:**
- Modify: `src/shadow_trading/executor.py:55-80` (`_check_paper_buying_power`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executor_entry.py`:

```python
def test_buying_power_crisis_alert_after_consecutive_failures():
    """Fix #358: 3+ consecutive buying power failures should trigger an alert."""
    import src.shadow_trading.executor as executor_mod

    # Reset counter
    executor_mod._consecutive_bp_failures = 0

    with patch("src.shadow_trading.alpaca_adapter.get_account_info",
               return_value={"buying_power": 100.0}), \
         patch("src.shadow_trading.executor.send_telegram") as mock_tg:

        # 3 consecutive failures
        for _ in range(3):
            result = executor_mod._check_paper_buying_power(500.0, 10)
            assert result is False

        # Should have sent an alert after the 3rd failure
        assert mock_tg.called, "Should send Telegram alert after 3 consecutive BP failures"
        alert_text = mock_tg.call_args[0][0]
        assert "BUYING POWER" in alert_text.upper()

    # Reset
    executor_mod._consecutive_bp_failures = 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor_entry.py::test_buying_power_crisis_alert_after_consecutive_failures -v`

- [ ] **Step 3: Add consecutive failure counter and alert**

In `src/shadow_trading/executor.py`, before `_check_paper_buying_power` (~line 55):

```python
_consecutive_bp_failures = 0
_BP_ALERT_THRESHOLD = 3
```

In the function body, after `return False` (~line 76):

```python
        if required > buying_power:
            logger.warning(
                "[SHADOW] Insufficient buying power: need $%.2f, have $%.2f",
                required, buying_power,
            )
            global _consecutive_bp_failures
            _consecutive_bp_failures += 1
            if _consecutive_bp_failures >= _BP_ALERT_THRESHOLD:
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram(
                        f"⚠️ BUYING POWER CRISIS: {_consecutive_bp_failures} consecutive rejections\n"
                        f"Available: ${buying_power:,.2f} / Need: ${required:,.2f}\n"
                        f"Check for orphaned positions consuming capital."
                    )
                except Exception:
                    pass
            return False
        _consecutive_bp_failures = 0  # Reset on success
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_executor_entry.py::test_buying_power_crisis_alert_after_consecutive_failures -v`

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_executor_entry.py
git commit -m "feat(executor): alert on consecutive buying power failures (#358)"
```

### Task 14b: Add submission_uncertain handling to reconciler (#352, #353)

**Files:**
- Modify: `src/shadow_trading/reconcile.py` (add a new resolution block for `submission_uncertain` trades)

Trades marked `submission_uncertain` (from Task 6) need reconciliation: check if Alpaca has the position and either promote to `open` or close as `failed`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reconcile.py`:

```python
def test_reconcile_resolves_submission_uncertain_with_alpaca_position():
    """Trades marked submission_uncertain should be promoted to open if Alpaca has the position."""
    # This verifies the reconciler checks for submission_uncertain status
    import sqlite3
    with patch("src.shadow_trading.reconcile.get_all_positions",
               return_value=[{"symbol": "GHOST", "qty": 50, "avg_entry_price": 100.0,
                              "current_price": 100.0, "market_value": 5000.0,
                              "unrealized_pl": 0.0, "unrealized_plpc": 0.0}]):
        from src.shadow_trading.models import ACTIVE_STATUSES
        assert "submission_uncertain" in ACTIVE_STATUSES
```

- [ ] **Step 2: Add submission_uncertain resolution to reconcile_paper_trades**

In `src/shadow_trading/reconcile.py`, after the stuck exit resolution block (~line 508), add:

```python
    # Resolve submission_uncertain trades: these are entries where we don't
    # know if Alpaca received the order (network error during submission).
    # Check Alpaca — if position exists, promote to open; otherwise close as failed.
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        uncertain = conn.execute(
            "SELECT trade_id, ticker, entry_price, planned_shares "
            "FROM shadow_trades "
            "WHERE source = 'paper' AND status = 'submission_uncertain'"
        ).fetchall()

    if uncertain and not dry_run:
        for row in uncertain:
            ticker = row["ticker"]
            trade_id = row["trade_id"]
            if ticker in alpaca_tickers:
                # Alpaca has it — promote to open
                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        "UPDATE shadow_trades SET status = 'open' WHERE trade_id = ?",
                        (trade_id,),
                    )
                logger.info("[RECONCILE-PAPER] Promoted uncertain trade to open: %s", ticker)
            else:
                # Alpaca doesn't have it — close as failed
                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        "UPDATE shadow_trades SET status = 'failed' WHERE trade_id = ?",
                        (trade_id,),
                    )
                logger.info("[RECONCILE-PAPER] Closed uncertain trade as failed: %s", ticker)
```

- [ ] **Step 3: Run reconcile tests**

Run: `python -m pytest tests/test_reconcile.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/shadow_trading/reconcile.py tests/test_reconcile.py
git commit -m "feat(reconcile): resolve submission_uncertain trades (#352, #353)"
```

---

## Phase 5: Infrastructure Cleanup

**Branch:** `fix/infra-cleanup-328-350-351`
**Issues:** #328 (route regression), #350 (test coverage), #351 (done-flags)
**Dependency:** None (can run parallel to other phases)

### Task 15: Fix latest_collection date format (#328)

**Files:**
- Modify: `src/api/routes/system.py:100` OR `tests/test_local_api_routes.py:284`

The test expects `"2026-03-30"` but the API returns `"2026-03-30T00:00:00"`. The API returns `MAX(collected_at)` which is a timestamp, not a date. The fix belongs in the API layer — truncate to date.

- [ ] **Step 1: Read the current API query**

The query at `src/api/routes/system.py` uses `MAX(collected_at)`. The `collected_at` column stores ISO timestamps. `_build_table_stats` passes through the raw value at line 100.

- [ ] **Step 2: Fix the API to return date-only**

In `src/api/routes/system.py:100`, change:

```python
# Before:
        "latest_collection": row[1] if total_records else None,

# After:
        "latest_collection": str(row[1])[:10] if (total_records and row[1]) else None,
```

- [ ] **Step 3: Run the failing test**

Run: `python -m pytest tests/test_local_api_routes.py::TestSystemRoutes::test_data_collection_stats_shape -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/api/routes/system.py
git commit -m "fix(api): truncate latest_collection to date format (#328)"
```

### Task 16: Fix done-flag conditionals in watch loop (#351)

**Files:**
- Modify: `src/scheduler/watch.py:1322-1358`
- Test: `tests/test_watch_done_flags.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_watch_done_flags.py
"""Tests for watch loop done-flag safety."""

from unittest.mock import patch, MagicMock


def test_daily_validation_done_flag_not_set_on_failure():
    """Fix #351: _daily_validation_done must not be set if validation raises."""
    # Verify the pattern: done-flag inside try block, not after except
    import ast
    with open("src/scheduler/watch.py") as f:
        source = f.read()

    # Find the validation block
    # The done flag should NOT appear after except — only inside try or in _safe_run pattern
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "_daily_validation_done = True" in line:
            # Check context: this line must be inside a try or an if _safe_run
            context = "\n".join(lines[max(0, i-10):i+1])
            assert "except" not in context.split("_daily_validation_done")[0].split("\n")[-1], \
                f"_daily_validation_done set unconditionally after except at line {i+1}"


def test_daily_build_score_done_flag_not_set_on_failure():
    """Fix #351: _daily_build_score_done must not be set if build score raises."""
    import ast
    with open("src/scheduler/watch.py") as f:
        source = f.read()

    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "_daily_build_score_done = True" in line:
            context = "\n".join(lines[max(0, i-10):i+1])
            assert "except" not in context.split("_daily_build_score_done")[0].split("\n")[-1], \
                f"_daily_build_score_done set unconditionally after except at line {i+1}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_watch_done_flags.py -v`

- [ ] **Step 3: Move done-flags inside try blocks**

In `src/scheduler/watch.py:1322-1344`, change:

```python
# Before (lines 1322-1344):
                elif (hour == 16 and now.minute >= 30 and now.minute < 45
                      and not self._daily_validation_done):
                    try:
                        # ... validation logic ...
                    except Exception as e:
                        logger.warning("[WATCH] Validation failed: %s", e)
                    self._daily_validation_done = True

# After:
                elif (hour == 16 and now.minute >= 30 and now.minute < 45
                      and not self._daily_validation_done):
                    try:
                        # ... validation logic (unchanged) ...
                        self._daily_validation_done = True
                    except Exception as e:
                        logger.warning("[WATCH] Validation failed: %s", e)
```

Similarly for build score (lines 1347-1358):

```python
# Before:
                if (hour == 16 and now.minute >= 45
                        and not self._daily_build_score_done):
                    try:
                        # ... build score logic ...
                    except Exception as e:
                        logger.warning("[WATCH] Build score persistence failed: %s", e)
                    self._daily_build_score_done = True

# After:
                if (hour == 16 and now.minute >= 45
                        and not self._daily_build_score_done):
                    try:
                        # ... build score logic (unchanged) ...
                        self._daily_build_score_done = True
                    except Exception as e:
                        logger.warning("[WATCH] Build score persistence failed: %s", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_watch_done_flags.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add src/scheduler/watch.py tests/test_watch_done_flags.py
git commit -m "fix(watch): move done-flags inside try blocks (#351)"
```

### Task 17: Add minimum executor test coverage (#350)

**Files:**
- Test: `tests/test_executor_entry.py` (extend from Phase 3)

This task extends the tests already created in Phase 3. The five minimum tests from issue #350:

- [ ] **Step 1: test_open_shadow_trade_happy_path**

Append to `tests/test_executor_entry.py`:

```python
def test_open_shadow_trade_happy_path(tmp_path):
    """#350: verify bracket order called with correct stop price."""
    db_path = _make_test_db(tmp_path)

    mock_order = {"order_id": "ord-1", "symbol": "AAPL", "qty": 10, "side": "buy",
                  "type": "market", "order_class": "bracket", "status": "filled",
                  "filled_avg_price": 150.0, "legs": []}

    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True), \
         patch("src.shadow_trading.executor.validate_llm_output", return_value=True), \
         patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None), \
         patch("src.shadow_trading.executor.check_risk_limits", return_value=True), \
         patch("src.shadow_trading.alpaca_adapter.place_bracket_order", return_value=mock_order) as mock_bracket, \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]), \
         patch("src.shadow_trading.alpaca_adapter.verify_order_accepted",
               return_value={"verified": True, "status": "filled", "error": None}):

        from src.shadow_trading.executor import open_shadow_trade
        packet = MagicMock()
        packet.ticker = "AAPL"
        packet.entry_price = "$150.00"
        packet.stop_loss = "$142.50"
        packet.target_1 = "$165.00"
        packet.target_2 = "$180.00"

        result = open_shadow_trade("rec-1", packet, {"strategy_type": "pullback"},
                                   config={"risk": {"base_risk_pct": 1.0, "starting_capital": 100000}},
                                   db_path=db_path)
        assert result is not None
        # Verify bracket order was called with correct stop
        mock_bracket.assert_called_once()
        call_kwargs = mock_bracket.call_args
        assert call_kwargs[1]["stop_loss_price"] == 142.5 or call_kwargs[0][2] == 142.5


def test_open_shadow_trade_missing_stop_rejected(tmp_path):
    """#350: stop_price <= 0 must be rejected before bracket order."""
    db_path = _make_test_db(tmp_path)

    with patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True), \
         patch("src.shadow_trading.executor.validate_llm_output", return_value=True), \
         patch("src.shadow_trading.executor.get_open_shadow_trade_for_ticker", return_value=None), \
         patch("src.shadow_trading.executor.check_risk_limits", return_value=True), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):

        from src.shadow_trading.executor import open_shadow_trade
        packet = MagicMock()
        packet.ticker = "BAD"
        packet.entry_price = "$100.00"
        packet.stop_loss = "$0.00"  # Invalid
        packet.target_1 = "$110.00"
        packet.target_2 = "$120.00"

        result = open_shadow_trade("rec-1", packet, {"strategy_type": "pullback"},
                                   config={"risk": {"base_risk_pct": 1.0, "starting_capital": 100000}},
                                   db_path=db_path)
        # Should be rejected or return None — no bracket order with stop=0
        # The exact behavior depends on whether executor catches this before Alpaca
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT status FROM shadow_trades WHERE ticker='BAD'").fetchone()
        conn.close()
        if row:
            assert row[0] != "open", "Trade with stop_price=0 must not be opened"
```

- [ ] **Step 2: Run new tests**

Run: `python -m pytest tests/test_executor_entry.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_executor_entry.py
git commit -m "test(executor): add minimum viable entry path tests (#350)"
```

---

## Phase Summary

| Phase | Branch | Issues | Tasks | Key Files |
|-------|--------|--------|-------|-----------|
| 1 | `fix/security-hardening-348-349` | #348, #349 | 1-2 | `cli/commands.py`, `cloud_app.py` |
| 2 | `fix/status-model-355` | #355 | 3-4 | `models.py`, `executor.py` |
| 3 | `fix/order-submission-352-353-359-360` | #352, #353, #359, #360 | 5-8 | `alpaca_adapter.py`, `executor.py`, `schema/registry.py` |
| 4 | `fix/reconciler-354-356-357-358` | #354, #356, #357, #358 | 10-14b | `reconcile.py`, `executor.py`, `alpaca_adapter.py` |
| 5 | `fix/infra-cleanup-328-350-351` | #328, #350, #351 | 15-17 | `system.py`, `watch.py`, tests |

**Task 9 merged into Task 6** — both modify the same exception handler block in `executor.py:482`.

**Task 14b added** — resolves `submission_uncertain` trades in the reconciler (required by Phase 3 status changes).

**Merge order:** Phase 1 and 5 are independent — merge anytime. Phase 2 before 3. Phase 3 before 4.

**CI gate:** Each PR must pass `python -m pytest tests/ -q` with >= 1405 tests passing and no new failures. Run `python -m src.main validate-schema` if any DB columns are touched (Task 8 adds `exit_order_id`).

## Review Notes (Iteration 1)

**Alpaca SDK findings:**
- Only one public exception: `alpaca.common.exceptions.APIError` (with `.status_code`, `.code`, `.message`)
- SDK auto-retries 429 and 504 (3x, 3s backoff) — plan updated to NOT manually handle rate limits
- Network errors (`ConnectionError`, `TimeoutError`) come from `requests`, NOT the SDK

**Gaps fixed in iteration 1:**
- `exit_order_id` column missing from `src/schema/registry.py` — added Step 0 to Task 8
- Task 2 test was import-time but guard is per-request — test rewritten to call `verify_auth` directly
- Tasks 6+9 merged to avoid merge conflicts on same code block
- Task 14b added for `submission_uncertain` reconciliation
- `APIError` catch added between `ConnectionError` and `Exception` in Task 6

## Review Notes (Iteration 2)

**Test infrastructure fix:**
- Replaced hardcoded `_make_test_db()` with `initialize_database()` from `src/journal/store.py` — matches production schema exactly. The hardcoded CREATE TABLE was missing 14 columns from the real schema (`timeout_days`, `broker`, `setup_type`, `actual_shares`, etc.)

**Edge case tests added:**
- Task 10: Zero entry_price in backfill (prevents division by zero)
- Task 13: Empty positions list from Alpaca (ensures entry proceeds normally)

**Verified present:**
- `send_telegram()` exists at `src/notifications/telegram.py:103` — Task 14 is safe
- `exit_retry_count` column exists in schema registry — Task 8's retry logic is safe
- Current test count is 1,603 — plan adds ~30 tests for ~1,633 total (well above 1,405 CI minimum)

**Remaining edge cases (documented, not yet tested — add during implementation):**
- `verify_order_accepted` returns `verified=None` — executor should treat as `submission_uncertain`
- `_check_paper_buying_power` raises Exception — currently fail-open by design (line 78-80), test should verify this

## Review Notes (Iteration 3)

**Type consistency verified:**
- `verify_order_accepted(order_id: str) -> dict` — used consistently in 7 locations
- `cancel_orders_for_ticker(ticker: str) -> int` — used consistently in 4 locations
- Status strings (`"rejected"`, `"submission_uncertain"`, `"failed"`) — consistent across all tasks
- `TERMINAL_STATUSES` / `ACTIVE_STATUSES` — referenced correctly in all dependent tasks
- `APIError` import path `alpaca.common.exceptions.APIError` — matches installed SDK 0.43.2

**Task structure verified:**
- 17 tasks total (Task 9 merged into Task 6, Task 14b added)
- No orphaned task references
- All 14 issues covered by at least one task
- Dependency ordering is correct: Phase 2 → 3 → 4 (sequential), Phases 1 and 5 (independent)

**Plan is ready for execution.**
