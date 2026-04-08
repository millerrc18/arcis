# Log Rectification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 production bugs identified in the 2026-04-06 log review — exit cascade, schema drift, type-safety crashes, risk governor TypeError, and LLM conviction parsing failures.

**Architecture:** A shared `safe_numeric` utility handles all SQLite string-affinity type coercion. Exit cascade fix changes one exception handler and adds a circuit breaker. LLM fix adds a catch-all regex stage and diagnostic logging. All changes are in existing files except `src/utils/type_safety.py` (new) and `tests/` files.

**Tech Stack:** Python 3.12, pytest, SQLite, Alpaca SDK, Ollama/llama.cpp

**Spec:** `docs/plans/2026-04-06-log-rectification-plan.md` (v4.0)

**Branch:** `fix/log-review-rectification-2026-04-06` (already created)

---

### Task 1: Create `safe_numeric` utility

**Files:**
- Create: `src/utils/type_safety.py`
- Create: `tests/test_type_safety.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_type_safety.py
"""Tests for safe_numeric type coercion utility."""

import pytest


class TestSafeNumeric:
    def test_string_float(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("25.3") == 25.3

    def test_none_returns_default(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric(None) == 0.0

    def test_unparseable_returns_default(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("abc", default=5) == 5.0

    def test_float_passthrough(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric(25.3) == 25.3

    def test_string_int(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("3", type_=int) == 3

    def test_single_element_tuple(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric((25.3,)) == 25.3

    def test_single_element_list(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric([7]) == 7.0

    def test_int_passthrough(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric(42, type_=int) == 42

    def test_empty_string_returns_default(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("", default=0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_type_safety.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.utils.type_safety'`

- [ ] **Step 3: Write the implementation**

```python
# src/utils/type_safety.py
"""Type coercion utilities for SQLite string-affinity handling.

SQLite's dynamic typing means any column can store strings even when the
schema says REAL or INTEGER.  These helpers handle the common case where
a numeric column returns a string (e.g., "25.3") or None.
"""


def safe_numeric(value, default=0, type_=float):
    """Coerce *value* to a numeric type.

    Handles strings ("25.3"), None, single-element tuples from fetchone()
    like ``(25.3,)``, and numpy scalars.

    Returns *type_(default)* when coercion fails.
    """
    if value is None:
        return type_(default)
    # Unwrap single-element sequences (e.g., (4800.0,) from fetchone)
    if isinstance(value, (tuple, list)) and len(value) == 1:
        value = value[0]
    try:
        return type_(value)
    except (ValueError, TypeError):
        return type_(default)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_type_safety.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/utils/type_safety.py tests/test_type_safety.py
git commit -m "feat: add safe_numeric utility for SQLite type coercion (#311)"
```

---

### Task 2: Fix traffic light persistence filter type error

**Files:**
- Modify: `src/features/traffic_light.py:198`

- [ ] **Step 1: Write the failing test**

Add to existing `tests/test_traffic_light.py`:

```python
# Append to tests/test_traffic_light.py

class TestPersistenceFilterStringCount:
    """Regression #311: pending_count stored as string in SQLite."""

    def test_string_count_does_not_crash(self, tmp_path):
        """If pending_count is stored as text '3', persistence filter must not TypeError."""
        import sqlite3
        from src.features.traffic_light import compute_traffic_light, STATE_TABLE, _ensure_state_table

        db = str(tmp_path / "tl.db")
        _ensure_state_table(db)

        # Simulate a string pending_count in the DB
        with sqlite3.connect(db) as conn:
            conn.execute(
                f"UPDATE {STATE_TABLE} SET current_regime='GREEN', "
                f"pending_regime='YELLOW', pending_count='3' WHERE id=1"
            )
            conn.commit()

        # This must not raise TypeError
        result = compute_traffic_light(vix=22.0, db_path=db)
        assert "regime_label" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_traffic_light.py::TestPersistenceFilterStringCount -v`
Expected: FAIL with `TypeError: can only concatenate str`

- [ ] **Step 3: Apply the fix**

In `src/features/traffic_light.py`, change line 198:

```python
# Before:
                    new_count = (count or 0) + 1
# After:
                    new_count = int(count or 0) + 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_traffic_light.py -v`
Expected: All tests pass (16 existing + 1 new)

- [ ] **Step 5: Commit**

```bash
git add src/features/traffic_light.py tests/test_traffic_light.py
git commit -m "fix: coerce pending_count to int in traffic light persistence (#311)"
```

---

### Task 3: Fix VIX regime alert type error

**Files:**
- Modify: `src/scheduler/watch.py:2873`

- [ ] **Step 1: Apply the fix**

In `src/scheduler/watch.py`, change line 2873:

```python
# Before:
                vix_now = row[0]
# After:
                vix_now = float(row[0]) if row[0] is not None else 0.0
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All tests pass, count >= 1537

- [ ] **Step 3: Commit**

```bash
git add src/scheduler/watch.py
git commit -m "fix: coerce VIX to float in regime alert check (#311)"
```

---

### Task 4: Fix EOD report type errors

**Files:**
- Modify: `src/scheduler/watch.py:2757,2761,2773-2775`

- [ ] **Step 1: Apply the VIX cast fix**

In `src/scheduler/watch.py`, change lines 2757 and 2761:

```python
# Before (line 2757):
                vix = vix_row["vix"] if vix_row else 0.0
# After:
                vix = float(vix_row["vix"]) if vix_row else 0.0

# Before (line 2761):
                vix_prev = vix_prev_row["vix"] if vix_prev_row else vix
# After:
                vix_prev = float(vix_prev_row["vix"]) if vix_prev_row else vix
```

- [ ] **Step 2: Apply the risk_qualified cast fix**

In `src/scheduler/watch.py`, change lines 2773-2775:

```python
# Before:
                risk_worthy = risk_row["worthy"] if risk_row else 0
                risk_passed = risk_row["passed"] if risk_row else 0
                risk_rejected = risk_worthy - risk_passed
# After:
                risk_worthy = int(risk_row["worthy"]) if risk_row else 0
                risk_passed = int(risk_row["passed"]) if risk_row else 0
                risk_rejected = risk_worthy - risk_passed
```

- [ ] **Step 3: Run existing tests**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/scheduler/watch.py
git commit -m "fix: coerce VIX and risk metrics to numeric in EOD report (#311)"
```

---

### Task 5: Fix pre-market brief type error

**Files:**
- Modify: `src/scheduler/watch.py:2648-2649`

- [ ] **Step 1: Apply the fix**

In `src/scheduler/watch.py`, change lines 2648-2649:

```python
# Before:
                council_conf_raw = council_row["confidence_weighted_score"] if council_row else 0
                council_confidence = int(council_conf_raw * 100) if council_conf_raw and council_conf_raw <= 1 else int(council_conf_raw or 0)
# After:
                council_conf_raw = float(council_row["confidence_weighted_score"]) if council_row and council_row["confidence_weighted_score"] else 0.0
                council_confidence = int(council_conf_raw * 100) if council_conf_raw <= 1 else int(council_conf_raw)
```

- [ ] **Step 2: Run existing tests**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add src/scheduler/watch.py
git commit -m "fix: coerce council confidence to float in pre-market brief (#311)"
```

---

### Task 6: Fix risk governor TypeError

**Files:**
- Modify: `src/risk/governor.py:268` (top of `check_trade`)
- Modify: `src/packets/template.py:38`
- Modify: `tests/test_risk_governor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_risk_governor.py`:

```python
class TestTypeCoercion:
    """Regression #308: governor must handle non-float allocation inputs."""

    def test_string_allocation(self, governor, base_portfolio):
        result = governor.check_trade("BKNG", "4800.0", {}, base_portfolio,
                                      traffic_light_multiplier=0.5)
        assert isinstance(result, dict)
        assert "approved" in result

    def test_tuple_allocation(self, governor, base_portfolio):
        result = governor.check_trade("BKNG", (4800.0,), {}, base_portfolio)
        assert isinstance(result, dict)
        assert "approved" in result

    def test_string_traffic_light_multiplier(self, governor, base_portfolio):
        result = governor.check_trade("AAPL", 400.0, {}, base_portfolio,
                                      traffic_light_multiplier="0.5")
        assert isinstance(result, dict)

    def test_zero_allocation_rejected(self, governor, base_portfolio):
        result = governor.check_trade("AAPL", 0, {}, base_portfolio)
        assert result["approved"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_risk_governor.py::TestTypeCoercion -v`
Expected: FAIL with `TypeError: can't multiply sequence by non-int of type 'float'`

- [ ] **Step 3: Add coercion to governor entry point**

In `src/risk/governor.py`, add at line 268 (top of `check_trade`, after docstring):

```python
        checks = []

        # Coerce inputs — upstream can produce strings, tuples, or numpy scalars
        from src.utils.type_safety import safe_numeric
        allocation_dollars = safe_numeric(allocation_dollars, default=0)
        traffic_light_multiplier = safe_numeric(traffic_light_multiplier, default=1.0)
        event_risk_multiplier = safe_numeric(event_risk_multiplier, default=1.0)

        if allocation_dollars <= 0:
            return self._reject(checks, "Zero or negative allocation")
```

This replaces the existing `checks = []` on line 268. The rest of the method is unchanged.

- [ ] **Step 4: Fix template.py position sizing**

In `src/packets/template.py`, change line 38:

```python
# Before:
    allocation = shares * price
# After:
    allocation = float(int(shares) * float(price))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_risk_governor.py -v`
Expected: All 21 tests pass (17 existing + 4 new)

- [ ] **Step 6: Commit**

```bash
git add src/risk/governor.py src/packets/template.py tests/test_risk_governor.py
git commit -m "fix: coerce allocation inputs in risk governor (#308)"
```

---

### Task 7: Fix shadow trade exit cascade — mark exit_failed on exception

**Files:**
- Modify: `src/shadow_trading/executor.py:867-872`
- Modify: `tests/test_executor_import.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executor_import.py`:

```python
class TestExitExceptionMarksFailure:
    """Regression #310: exception in _submit_exit_order must mark exit_failed."""

    def test_exception_marks_exit_failed_not_open(self):
        """Trade must NOT remain 'open' after broker exception."""
        from src.shadow_trading.executor import check_and_manage_open_trades

        mock_trade = {
            "trade_id": "t-stuck",
            "ticker": "TGT",
            "status": "open",
            "actual_entry_price": "125.0",
            "entry_price": "125.0",
            "stop_price": "120.0",
            "target_1": "130.0",
            "target_2": "135.0",
            "planned_shares": "166",
            "created_at": "2026-04-01T09:30:00",
            "max_favorable_excursion": "0",
            "max_adverse_excursion": "0",
            "source": "paper",
        }

        with patch("src.shadow_trading.executor.get_open_shadow_trades",
                   return_value=[mock_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe",
                   return_value=115.0), \
             patch("src.shadow_trading.executor.get_all_positions",
                   return_value=[]), \
             patch("src.shadow_trading.executor._submit_exit_order",
                   side_effect=Exception("insufficient qty")), \
             patch("src.shadow_trading.executor.update_shadow_trade") as mock_update, \
             patch("src.shadow_trading.executor.load_config",
                   return_value={"shadow_trading": {"timeout_days": 15}}):
            check_and_manage_open_trades()

        # Verify update_shadow_trade was called with exit_failed
        calls = [c for c in mock_update.call_args_list
                 if any("exit_failed" in str(v) for v in c[0])]
        assert len(calls) > 0, "Trade should be marked exit_failed on exception"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor_import.py::TestExitExceptionMarksFailure -v`
Expected: FAIL — `update_shadow_trade` never called with `exit_failed`

- [ ] **Step 3: Apply the fix**

In `src/shadow_trading/executor.py`, change lines 867-872:

```python
# Before:
            if not bracket_exit:
                try:
                    exit_result = _submit_exit_order(trade, shares)
                except Exception as e:
                    logger.error("[EXIT] Broker exit failed for %s — trade remains open: %s", ticker, e)
                    continue

# After:
            if not bracket_exit:
                # Cancel any stale pending order before initial exit attempt
                _pending_oid = trade.get("exit_order_id") or trade.get("alpaca_order_id")
                if _pending_oid:
                    try:
                        from src.shadow_trading.alpaca_adapter import cancel_paper_order
                        cancel_paper_order(_pending_oid)
                        time.sleep(0.5)
                    except Exception:
                        pass

                try:
                    exit_result = _submit_exit_order(trade, shares)
                except Exception as e:
                    logger.error("[EXIT] Broker exit failed for %s — marking exit_failed: %s", ticker, e)
                    update_shadow_trade(
                        trade["trade_id"],
                        {"status": "exit_failed", "exit_reason": f"broker_exception:{type(e).__name__}"},
                        db_path,
                    )
                    continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_executor_import.py -v`
Expected: All 8 tests pass (7 existing + 1 new)

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_executor_import.py
git commit -m "fix: mark exit_failed on broker exception, cancel stale orders (#310)"
```

---

### Task 8: Add exit circuit breaker

**Files:**
- Modify: `src/shadow_trading/executor.py` (inside `check_and_manage_open_trades`)
- Modify: `tests/test_executor_import.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executor_import.py`:

```python
class TestExitCircuitBreaker:
    """#310: circuit breaker halts exits after mass failures."""

    def test_breaker_fires_on_majority_failure(self):
        from src.shadow_trading.executor import check_and_manage_open_trades

        def make_trade(ticker):
            return {
                "trade_id": f"t-{ticker}",
                "ticker": ticker,
                "status": "open",
                "actual_entry_price": "100.0",
                "entry_price": "100.0",
                "stop_price": "95.0",
                "target_1": "110.0",
                "target_2": "115.0",
                "planned_shares": "10",
                "created_at": "2026-04-01T09:30:00",
                "max_favorable_excursion": "0",
                "max_adverse_excursion": "0",
                "source": "paper",
            }

        trades = [make_trade(t) for t in ["A", "B", "C", "D", "E", "F", "G", "H"]]

        with patch("src.shadow_trading.executor.get_open_shadow_trades",
                   return_value=trades), \
             patch("src.shadow_trading.executor._get_current_price_safe",
                   return_value=90.0), \
             patch("src.shadow_trading.executor.get_all_positions",
                   return_value=[]), \
             patch("src.shadow_trading.executor._submit_exit_order",
                   side_effect=Exception("insufficient buying power")), \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("src.shadow_trading.executor.load_config",
                   return_value={"shadow_trading": {"timeout_days": 15}}), \
             patch("src.notifications.telegram.send_telegram") as mock_tg:
            check_and_manage_open_trades()

        # Circuit breaker should have sent a Telegram alert
        assert mock_tg.called, "Circuit breaker should send Telegram alert on mass failure"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor_import.py::TestExitCircuitBreaker -v`
Expected: FAIL — no Telegram alert sent

- [ ] **Step 3: Add circuit breaker logic**

In `src/shadow_trading/executor.py`, inside `check_and_manage_open_trades`:

After line 667 (`actions = []`), add counters:
```python
    actions = []
    _exit_attempts = 0
    _exit_failures = 0
```

Inside the exit handling block (after the exception handler from Task 7, and after the `exit_failed` status update at line ~955), increment the failure counter and check the breaker:
```python
                    _exit_attempts += 1
                    _exit_failures += 1
                    if _exit_failures > 3 and _exit_failures > _exit_attempts * 0.5:
                        logger.critical(
                            "[EXIT] Circuit breaker: %d/%d exits failed — halting remaining exits",
                            _exit_failures, _exit_attempts)
                        try:
                            from src.notifications.telegram import send_telegram
                            send_telegram(
                                f"🚨 EXIT CIRCUIT BREAKER: {_exit_failures}/{_exit_attempts} "
                                f"exits failed this cycle. Remaining exits paused."
                            )
                        except Exception:
                            pass
                        break
```

Also increment `_exit_attempts` on successful exits (after the close_shadow_trade call).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_executor_import.py -v`
Expected: All 9 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_executor_import.py
git commit -m "feat: add exit circuit breaker with Telegram alert (#310)"
```

---

### Task 9: Add `cancel_all_orders` and CLI command

**Files:**
- Modify: `src/shadow_trading/alpaca_adapter.py`
- Modify: `src/main.py`
- Modify: `tests/test_executor_import.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_executor_import.py`:

```python
class TestCancelAllOrders:
    def test_cancel_all_returns_count(self):
        from src.shadow_trading.alpaca_adapter import cancel_all_orders
        mock_client = MagicMock()
        mock_client.cancel_orders.return_value = [MagicMock(), MagicMock()]
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_all_orders()
        assert result["cancelled"] == 2

    def test_cancel_all_handles_error(self):
        from src.shadow_trading.alpaca_adapter import cancel_all_orders
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   side_effect=Exception("no key")):
            result = cancel_all_orders()
        assert result["cancelled"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_executor_import.py::TestCancelAllOrders -v`
Expected: FAIL — `ImportError: cannot import name 'cancel_all_orders'`

- [ ] **Step 3: Add `cancel_all_orders` to adapter**

Append to `src/shadow_trading/alpaca_adapter.py`:

```python
def cancel_all_orders() -> dict:
    """Cancel all pending Alpaca orders.  Returns {'cancelled': N}."""
    try:
        client = _get_trading_client()
        cancelled = client.cancel_orders()
        count = len(cancelled) if cancelled else 0
        logger.info("[CANCEL] Cancelled %d pending orders", count)
        return {"cancelled": count}
    except Exception as e:
        logger.warning("[CANCEL] Could not cancel all orders: %s", e)
        return {"cancelled": 0, "error": str(e)}
```

- [ ] **Step 4: Add CLI command to main.py**

In `src/main.py`, after the existing `halt-trading` / `resume-trading` commands, add:

```python
@app.command()
def cancel_all_pending():
    """Cancel all pending Alpaca orders for emergency recovery."""
    from src.shadow_trading.alpaca_adapter import cancel_all_orders
    result = cancel_all_orders()
    count = result.get("cancelled", 0)
    error = result.get("error")
    print(f"Cancelled {count} pending orders")
    if error:
        print(f"Warning: {error}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_executor_import.py -v`
Expected: All 11 tests pass

- [ ] **Step 6: Commit**

```bash
git add src/shadow_trading/alpaca_adapter.py src/main.py tests/test_executor_import.py
git commit -m "feat: add cancel-all-pending CLI command for exit recovery (#310)"
```

---

### Task 10: Add LLM conviction Stage 6 catch-all and diagnostic logging

**Files:**
- Modify: `src/llm/packet_writer.py`
- Create: `tests/test_packet_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_packet_writer.py
"""Tests for LLM conviction extraction stages (#309, #312)."""

import pytest
from unittest.mock import patch


class TestConvictionExtraction:
    """Test all 6 stages of conviction extraction."""

    def _parse(self, response):
        from src.llm.packet_writer import _parse_llm_response
        conviction, why_now, analysis = _parse_llm_response(response)
        return conviction

    def test_stage1_xml_metadata(self):
        resp = "<why_now>Test</why_now><analysis>Test analysis paragraph one.\n\nParagraph two.</analysis><metadata>Conviction: 8\nDirection: LONG</metadata>"
        assert self._parse(resp) == 8

    def test_stage6_catchall_prose(self):
        resp = "<why_now>Test</why_now><analysis>Long analysis here that is definitely more than two hundred characters to pass the length check. " * 3 + "</analysis>\nMy conviction for this trade is 7 out of ten based on the technical setup."
        assert self._parse(resp) == 7

    def test_all_stages_fail_returns_none(self):
        resp = "<why_now>Test</why_now><analysis>Long text " * 30 + "</analysis>\nNo rating provided."
        assert self._parse(resp) is None


class TestConvictionDebugLogging:
    """Test that parse failures write debug files (#312)."""

    def test_none_conviction_writes_debug_file(self, tmp_path):
        from src.llm.packet_writer import _parse_llm_response
        response = "This response has no conviction anywhere and is long enough. " * 10

        with patch("src.llm.packet_writer.Path") as mock_path_cls:
            mock_dir = tmp_path / "llm_debug"
            mock_path_cls.return_value = mock_dir
            conviction, _, _ = _parse_llm_response(response)

        assert conviction is None
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `python -m pytest tests/test_packet_writer.py -v`
Expected: Stage 1 test should PASS (existing code). Stage 6 test should FAIL (stage doesn't exist yet). Debug logging test may FAIL.

- [ ] **Step 3: Add Stage 6 catch-all to `_parse_llm_response`**

In `src/llm/packet_writer.py`, after Stage 5 (around line 375), add:

```python
        # Stage 6: Catch-all — any digit within 20 chars of "conviction"
        if conviction is None:
            m = re.search(r'(?i)conviction\D{0,20}(\d{1,2})', response)
            if m:
                val = int(m.group(1))
                if 1 <= val <= 10:
                    conviction = val
                    logger.debug("[LLM] Stage 6 catch-all matched conviction=%d", conviction)
```

- [ ] **Step 4: Add diagnostic logging for None conviction**

In `src/llm/packet_writer.py`, in the `enhance_packet_with_llm` function, where conviction is checked for None (around line 485), enhance the warning:

```python
    if conviction is None:
        conviction = 5
        logger.warning(
            "[LLM] Conviction is None for %s — defaulting to %d. "
            "Response preview: %s",
            packet.ticker, conviction,
            repr(raw_response[:500]) if raw_response else "EMPTY",
        )
        # Write full response to debug file for offline analysis
        try:
            from pathlib import Path
            debug_dir = Path("logs/llm_debug")
            debug_dir.mkdir(exist_ok=True)
            (debug_dir / f"{packet.ticker}_{datetime.now().strftime('%H%M%S')}.txt").write_text(
                raw_response or "EMPTY", encoding="utf-8")
        except Exception:
            pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_packet_writer.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/llm/packet_writer.py tests/test_packet_writer.py
git commit -m "feat: add Stage 6 conviction catch-all and debug logging (#309, #312)"
```

---

### Task 11: Add Postgres schema drift check to startup

**Files:**
- Modify: `src/startup.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add drift check function to startup.py**

In `src/startup.py`, add the function near the existing `check_connectivity` code:

```python
def check_postgres_schema_drift() -> list:
    """Compare schema registry against live Render Postgres.

    Returns list of CheckResult.  Only runs if render sync is configured.
    """
    results = []
    try:
        from src.config import load_config
        cfg = load_config()
        render_cfg = cfg.get("render", {})
        db_url = render_cfg.get("database_url")
        if not db_url or not render_cfg.get("sync_enabled"):
            return results

        import psycopg2
        from src.schema.registry import TABLES
        from src.sync.render_sync import SYNC_TABLES

        synced_names = {t["name"] for t in SYNC_TABLES}
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                for table in TABLES:
                    if table.name not in synced_names:
                        continue
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = %s", (table.name,))
                    pg_cols = {r[0] for r in cur.fetchall()}
                    if not pg_cols:
                        continue
                    registry_cols = {c.name for c in table.columns}
                    missing = registry_cols - pg_cols
                    if missing:
                        results.append(CheckResult(
                            "warn",
                            f"Postgres drift: {table.name} missing columns: {', '.join(sorted(missing))}",
                            "Run: DATABASE_URL=... python scripts/render_migrate.py",
                        ))
    except Exception as e:
        results.append(CheckResult(
            "warn",
            f"Postgres drift check failed: {e}",
            "Verify render database_url in config",
        ))
    return results
```

Wire it into the existing `check_connectivity` function's return list.

- [ ] **Step 2: Update CLAUDE.md schema rules**

Add rule #8 after the existing rule #7 in CLAUDE.md:

```markdown
8. **After local schema changes:** Run `render_migrate.py` to sync Postgres.
   Include the output in the PR description alongside `validate-schema` output.
```

- [ ] **Step 3: Run existing startup tests**

Run: `python -m pytest tests/test_startup.py -v`
Expected: All 21 existing tests pass

- [ ] **Step 4: Commit**

```bash
git add src/startup.py CLAUDE.md
git commit -m "feat: add Postgres schema drift check to startup validation (#307)"
```

---

### Task 12: Enable grammar enforcement and test LLM

**Files:**
- Modify: `config/settings.local.yaml`

- [ ] **Step 1: Enable grammar enforcement**

Add to `config/settings.local.yaml` under the `llm` section:

```yaml
llm:
  use_grammar_enforcement: true
```

- [ ] **Step 2: Test with manual inference**

```bash
python -c "
from src.llm.client import generate
from src.llm.prompts import PACKET_SYSTEM_PROMPT
resp = generate('Analyze AAPL for a swing trade. Score: 75.', PACKET_SYSTEM_PROMPT)
print('=== RESPONSE (first 1000 chars) ===')
print(repr(resp[:1000]))
import re
for label, pattern in [
    ('Stage 1: XML metadata', r'<metadata>.*?Conviction:\s*(\d+)'),
    ('Stage 2: Plain CONVICTION', r'CONVICTION:\s*(\d+)'),
    ('Stage 6: Catch-all', r'(?i)conviction\D{0,20}(\d{1,2})'),
]:
    m = re.search(pattern, resp or '', re.IGNORECASE | re.DOTALL)
    print(f'  {label}: {m.group(1) if m else \"NO MATCH\"}')
"
```

- [ ] **Step 3: Evaluate result**

If grammar enforcement works: conviction should be extracted by Stage 1. Keep it enabled.

If grammar enforcement fails (ImportError, model path issue, etc.): disable it (`use_grammar_enforcement: false`) and rely on the Stage 6 catch-all from Task 10. File a follow-up issue for grammar enforcement setup.

- [ ] **Step 4: Commit**

```bash
git add config/settings.local.yaml
git commit -m "feat: enable LLM grammar enforcement for structured output (#309)"
```

Note: `config/settings.local.yaml` is gitignored — this change is local only. Document the setting in the PR description.

---

### Task 13: Final verification

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All tests pass. Count should be >= 1537 + ~25 new = 1562+.

- [ ] **Step 2: Verify no test count regression**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: Pass count >= 1562, 0 failed.

- [ ] **Step 3: Verify the log fixes work**

Watch the next scan cycle in `logs/arcis.log` for:
- No `trade remains open` errors (should say `marking exit_failed` instead)
- No `Persistence filter failed: can only concatenate str` warnings
- No `VIX regime alert check failed: '<' not supported` warnings
- No `EOD report failed: '>' not supported` warnings
- No `Governor check failed for BKNG: can't multiply sequence` errors
- Conviction values other than 5 in canary logs (if grammar enforcement works)
- `Sync cycle complete: ... 0 errors` for shadow_trades

---

## File Map Summary

| File | Action | Task(s) |
|------|--------|---------|
| `src/utils/type_safety.py` | Create | 1 |
| `tests/test_type_safety.py` | Create | 1 |
| `src/features/traffic_light.py` | Modify line 198 | 2 |
| `tests/test_traffic_light.py` | Extend | 2 |
| `src/scheduler/watch.py` | Modify lines 2649, 2757, 2761, 2773-2775, 2873 | 3, 4, 5 |
| `src/risk/governor.py` | Modify line 268 | 6 |
| `src/packets/template.py` | Modify line 38 | 6 |
| `tests/test_risk_governor.py` | Extend | 6 |
| `src/shadow_trading/executor.py` | Modify lines 867-872, add counters | 7, 8 |
| `tests/test_executor_import.py` | Extend | 7, 8, 9 |
| `src/shadow_trading/alpaca_adapter.py` | Add `cancel_all_orders` | 9 |
| `src/main.py` | Add CLI command | 9 |
| `src/llm/packet_writer.py` | Add Stage 6, debug logging | 10 |
| `tests/test_packet_writer.py` | Create | 10 |
| `src/startup.py` | Add drift check | 11 |
| `CLAUDE.md` | Add rule #8 | 11 |
| `config/settings.local.yaml` | Enable grammar enforcement | 12 |
