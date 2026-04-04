# Remaining Issues Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 remaining GitHub issues (#188, #187, #147, #132, #106) with comprehensive hardening — validation, tests, and defensive infrastructure.

**Architecture:** Each issue is an independent task with its own tests and commit. A shared retry utility (`src/utils/retry.py`) is created first since it's needed by #147. Changes stay within existing module boundaries and follow current patterns.

**Tech Stack:** Python 3.12, SQLite, pytest, no new dependencies

---

### Task 1: Retry utility with exponential backoff (#147)

**Files:**
- Create: `src/utils/retry.py`
- Create: `tests/test_retry.py`

- [ ] **Step 1: Write failing tests for retry utility**

```python
# tests/test_retry.py
"""Tests for exponential backoff retry utility."""

import time
from unittest.mock import MagicMock, patch

from src.utils.retry import retry_with_backoff


class TestRetryWithBackoff:
    def test_succeeds_on_first_try(self):
        fn = MagicMock(return_value="ok")
        result = retry_with_backoff(fn, max_retries=3)
        assert result == "ok"
        assert fn.call_count == 1

    def test_retries_then_succeeds(self):
        fn = MagicMock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "ok"])
        result = retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 3

    def test_exhausts_retries_returns_none(self):
        fn = MagicMock(side_effect=ConnectionError("always fails"))
        result = retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result is None
        assert fn.call_count == 3

    def test_only_catches_specified_exceptions(self):
        fn = MagicMock(side_effect=ValueError("not retryable"))
        try:
            retry_with_backoff(fn, max_retries=3, base_delay=0.01, exceptions=(ConnectionError,))
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        assert fn.call_count == 1

    def test_delay_increases_exponentially(self):
        fn = MagicMock(side_effect=[ConnectionError("1"), ConnectionError("2"), "ok"])
        delays = []
        original_sleep = time.sleep
        with patch("src.utils.retry.time.sleep", side_effect=lambda d: delays.append(d)):
            retry_with_backoff(fn, max_retries=3, base_delay=1.0, max_delay=30.0)
        assert len(delays) == 2
        # Second delay should be roughly 2x the first (with jitter)
        assert delays[1] > delays[0] * 1.5

    def test_delay_capped_at_max(self):
        fn = MagicMock(side_effect=ConnectionError("fail"))
        delays = []
        with patch("src.utils.retry.time.sleep", side_effect=lambda d: delays.append(d)):
            retry_with_backoff(fn, max_retries=10, base_delay=1.0, max_delay=5.0)
        assert all(d <= 6.0 for d in delays)  # max_delay + jitter headroom
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_retry.py -v`
Expected: ImportError — `src.utils.retry` does not exist yet

- [ ] **Step 3: Implement retry utility**

```python
# src/utils/retry.py
"""Exponential backoff retry utility.

Called by: data_enrichment.news, data_enrichment.insiders, data_enrichment.fundamentals,
           data_enrichment.macro, data_collection.*
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_retry.py
"""

import logging
import random
import time

logger = logging.getLogger(__name__)


def retry_with_backoff(
    fn,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
):
    """Call fn with exponential backoff on failure.

    Args:
        fn: Callable to execute (no arguments — use functools.partial or lambda)
        max_retries: Maximum number of attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Result of fn(), or None if all retries exhausted
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except exceptions as exc:
            if attempt == max_retries - 1:
                logger.warning("[RETRY] %s failed after %d attempts: %s",
                               fn.__name__ if hasattr(fn, '__name__') else 'fn',
                               max_retries, exc)
                return None
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = delay * random.uniform(-0.2, 0.2)
            actual_delay = max(0.1, delay + jitter)
            logger.warning("[RETRY] %s attempt %d/%d failed: %s — retrying in %.1fs",
                           fn.__name__ if hasattr(fn, '__name__') else 'fn',
                           attempt + 1, max_retries, exc, actual_delay)
            time.sleep(actual_delay)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_retry.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Apply backoff to enrichment modules**

Modify `src/data_enrichment/news.py` — wrap the Finnhub API call. Find the `requests.get()` call for news data and wrap it:

```python
from src.utils.retry import retry_with_backoff

# Replace direct requests.get() with:
resp = retry_with_backoff(
    lambda: requests.get(url, headers=headers, timeout=15),
    max_retries=3,
    base_delay=2.0,
    exceptions=(requests.RequestException, ConnectionError, OSError),
)
if resp is None or resp.status_code != 200:
    return []
```

Apply the same pattern to:
- `src/data_enrichment/insiders.py` — Finnhub insider API call
- `src/data_enrichment/fundamentals.py` — API calls
- `src/data_enrichment/macro.py` — FRED API calls
- `src/data_collection/analyst_collector.py` — Finnhub analyst API call
- `src/data_collection/insider_collector.py` — Finnhub insider collection
- `src/data_collection/short_interest_collector.py` — short interest API call

For each file: import `retry_with_backoff`, wrap the `requests.get()` call in a lambda, replace fixed `time.sleep()` with the backoff utility.

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -q --tb=short`
Expected: Pass count >= 1105, no new failures

- [ ] **Step 7: Commit**

```bash
git add src/utils/retry.py tests/test_retry.py src/data_enrichment/ src/data_collection/
git commit -m "feat: exponential backoff retry utility + apply to enrichment/collection (#147)"
```

---

### Task 2: Negative shares validation (#188)

**Files:**
- Modify: `src/shadow_trading/reconcile.py:25-37`
- Create: `tests/test_reconcile_backfill.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reconcile_backfill.py
"""Tests for reconcile backfill share validation."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.shadow_trading.reconcile import _backfill_trade_data

ET = ZoneInfo("America/New_York")


class TestBackfillSharesValidation:
    def test_positive_shares_returns_trade(self):
        now = datetime.now(ET)
        result = _backfill_trade_data("AAPL", 150.0, 10, 1500.0, "paper", now)
        assert result is not None
        assert result["planned_shares"] == 10
        assert result["ticker"] == "AAPL"

    def test_negative_shares_returns_none(self):
        now = datetime.now(ET)
        result = _backfill_trade_data("PFE", 25.0, -14, -350.0, "live", now)
        assert result is None

    def test_zero_shares_returns_none(self):
        now = datetime.now(ET)
        result = _backfill_trade_data("MSFT", 400.0, 0, 0.0, "paper", now)
        assert result is None
```

- [ ] **Step 2: Run tests — negative/zero should pass (no validation yet = returns dict)**

Run: `python -m pytest tests/test_reconcile_backfill.py -v`
Expected: `test_positive_shares_returns_trade` PASSES, other two FAIL

- [ ] **Step 3: Add validation to _backfill_trade_data**

In `src/shadow_trading/reconcile.py`, modify `_backfill_trade_data()`:

```python
def _backfill_trade_data(ticker, entry_price, qty, allocation, source, now):
    """Build a trade_data dict for backfilling an orphaned position."""
    if qty <= 0:
        logger.warning("[RECONCILE] Rejecting backfill for %s: qty=%s (long-only system)", ticker, qty)
        return None
    return {
        "trade_id": str(uuid4()), "ticker": ticker,
        # ... rest unchanged
    }
```

- [ ] **Step 4: Update callers to handle None**

In `reconcile_live_trades()` (around line 100-113), after `_backfill_trade_data()` is called, add:

```python
trade_data = _backfill_trade_data(ticker, entry_px, qty, ...)
if trade_data is None:
    continue
```

Apply the same guard to the paper backfill path (around line 259-271).

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_reconcile_backfill.py tests/test_reconcile.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/shadow_trading/reconcile.py tests/test_reconcile_backfill.py
git commit -m "fix: reject negative shares in reconcile backfill — long-only guard (#188)"
```

---

### Task 3: Buying power check + mark failed trades (#187)

**Files:**
- Modify: `src/shadow_trading/executor.py:249-275`
- Create: `tests/test_buying_power_check.py`
- Create: `scripts/mark_failed_trades.py`

- [ ] **Step 1: Write failing test for buying power check**

```python
# tests/test_buying_power_check.py
"""Tests for paper entry buying power validation."""

from unittest.mock import patch, MagicMock


class TestPaperBuyingPowerCheck:
    @patch("src.shadow_trading.alpaca_adapter.get_account_info")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_entry_rejected_when_insufficient_buying_power(self, mock_check, mock_acct):
        mock_acct.return_value = {"buying_power": 100.0, "equity": 1000.0}

        from src.shadow_trading.executor import _check_paper_buying_power
        result = _check_paper_buying_power(entry_price=150.0, shares=10)
        assert result is False

    @patch("src.shadow_trading.alpaca_adapter.get_account_info")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_entry_allowed_when_sufficient_buying_power(self, mock_check, mock_acct):
        mock_acct.return_value = {"buying_power": 5000.0, "equity": 10000.0}

        from src.shadow_trading.executor import _check_paper_buying_power
        result = _check_paper_buying_power(entry_price=150.0, shares=10)
        assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_buying_power_check.py -v`
Expected: ImportError — `_check_paper_buying_power` does not exist

- [ ] **Step 3: Add buying power check function**

In `src/shadow_trading/executor.py`, add near the top (after imports):

```python
def _check_paper_buying_power(entry_price: float, shares: int) -> bool:
    """Check if paper account has sufficient buying power for the trade."""
    try:
        from src.shadow_trading.alpaca_adapter import get_account_info
        acct = get_account_info()
        buying_power = acct.get("buying_power", 0)
        required = entry_price * shares
        if required > buying_power:
            logger.warning(
                "[SHADOW] Insufficient buying power: need $%.2f, have $%.2f",
                required, buying_power,
            )
            return False
        return True
    except Exception as exc:
        logger.warning("[SHADOW] Buying power check failed: %s — allowing trade", exc)
        return True  # Fail open to avoid blocking on API errors
```

- [ ] **Step 4: Wire buying power check into paper entry flow**

In `src/shadow_trading/executor.py`, before the bracket order attempt (around line 275), add:

```python
    # Buying power check before paper entry
    if not _check_paper_buying_power(entry_price, planned_shares):
        trade_data["status"] = "failed"
        trade_data["order_type"] = "rejected_buying_power"
        trade_data["actual_entry_price"] = entry_price
        trade_data["actual_entry_time"] = now.isoformat()
        trade_data["max_favorable_excursion"] = 0.0
        trade_data["max_adverse_excursion"] = 0.0
        insert_shadow_trade(trade_data, db_path)
        return trade_data
```

- [ ] **Step 5: Create migration script for 44 failed trades**

```python
# scripts/mark_failed_trades.py
"""One-time migration: mark existing failed trades as failed_permanent.

Usage: python scripts/mark_failed_trades.py [--dry-run]
"""

import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DB_PATH


def main():
    dry_run = "--dry-run" in sys.argv
    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE status = 'failed'"
        ).fetchone()[0]
        print(f"Found {count} trades with status='failed'")

        if dry_run:
            print("DRY RUN — no changes made")
            return

        conn.execute(
            "UPDATE shadow_trades SET status = 'failed_permanent' WHERE status = 'failed'"
        )
        print(f"Updated {count} trades to status='failed_permanent'")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_buying_power_check.py -v`
Expected: All PASS

- [ ] **Step 7: Run migration script**

```bash
python scripts/mark_failed_trades.py --dry-run
python scripts/mark_failed_trades.py
```

- [ ] **Step 8: Commit**

```bash
git add src/shadow_trading/executor.py tests/test_buying_power_check.py scripts/mark_failed_trades.py
git commit -m "fix: add paper buying power check + mark 44 failed trades permanent (#187)"
```

---

### Task 4: Placeholder config validation (#132)

**Files:**
- Modify: `src/config/__init__.py`
- Create: `tests/test_config_validation.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config_validation.py
"""Tests for configuration placeholder validation."""

import logging
from src.config import validate_config


class TestValidateConfig:
    def test_detects_placeholder_api_key(self):
        config = {"alpaca": {"api_key": "your-alpaca-api-key", "secret_key": "real-secret"}}
        warnings = validate_config(config)
        assert any("alpaca.api_key" in w for w in warnings)

    def test_detects_your_prefix_pattern(self):
        config = {"finnhub": {"api_key": "YOUR_FINNHUB_KEY"}}
        warnings = validate_config(config)
        assert len(warnings) >= 1

    def test_real_values_pass(self):
        config = {
            "alpaca": {"api_key": "PKAB1234567890", "secret_key": "abcdef1234567890"},
            "finnhub": {"api_key": "cs12345abcdef"},
        }
        warnings = validate_config(config)
        assert len(warnings) == 0

    def test_missing_keys_handled_gracefully(self):
        config = {}
        warnings = validate_config(config)
        # Should not crash, may or may not produce warnings
        assert isinstance(warnings, list)

    def test_empty_string_detected(self):
        config = {"alpaca": {"api_key": ""}}
        warnings = validate_config(config)
        assert any("alpaca.api_key" in w for w in warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_validation.py -v`
Expected: ImportError — `validate_config` does not exist

- [ ] **Step 3: Implement validate_config**

Add to `src/config/__init__.py`:

```python
import re
import logging

_logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"^your[-_]|placeholder|example|YOUR_|^$", re.IGNORECASE)

_CRITICAL_KEYS = [
    ("alpaca", "api_key"),
    ("alpaca", "secret_key"),
    ("finnhub", "api_key"),
    ("fred", "api_key"),
    ("anthropic", "api_key"),
    ("telegram", "bot_token"),
]


def validate_config(config: dict) -> list[str]:
    """Check critical config keys for placeholder values.

    Returns list of warning strings (key paths with placeholder values).
    Does not crash — returns empty list if config is missing sections.
    """
    warnings = []
    for section, key in _CRITICAL_KEYS:
        value = config.get(section, {}).get(key, None)
        if value is None:
            continue
        if not isinstance(value, str):
            continue
        if _PLACEHOLDER_RE.search(value) or value.strip() == "":
            warnings.append(f"{section}.{key} appears to be a placeholder")
    return warnings
```

- [ ] **Step 4: Wire into load_config()**

At the end of `load_config()`, before the return, add:

```python
    # Validate config for placeholder keys
    config_warnings = validate_config(_config_cache)
    for w in config_warnings:
        _logger.warning("[CONFIG] %s", w)
    if config_path == example_path:
        _logger.warning("[CONFIG] Using example config — API keys are placeholders")
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_config_validation.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/config/__init__.py tests/test_config_validation.py
git commit -m "feat: validate config keys for placeholder values on load (#132)"
```

---

### Task 5: Atomic kill switch with staleness check (#106)

**Files:**
- Modify: `src/risk/governor.py:40-52`
- Modify: `tests/test_governor.py` (or create `tests/test_kill_switch.py`)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kill_switch.py
"""Tests for atomic kill switch implementation."""

import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from src.risk import governor

ET = ZoneInfo("America/New_York")


class TestAtomicKillSwitch:
    def setup_method(self):
        self._orig = governor._HALT_FILE
        self._test_file = "data/test_halt_switch"
        governor._HALT_FILE = self._test_file
        # Clean up before each test
        for f in [self._test_file, self._test_file + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)

    def teardown_method(self):
        governor._HALT_FILE = self._orig
        for f in [self._test_file, self._test_file + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)

    def test_halt_creates_file_with_timestamp(self):
        governor._global_halt(True, source="test", reason="unit test")
        path = governor._get_halt_path()
        assert path.exists()
        data = json.loads(path.read_text())
        assert "halted_at" in data
        assert data["source"] == "test"

    def test_resume_removes_file(self):
        governor._global_halt(True, source="test")
        assert governor._is_halted()
        governor._global_halt(False)
        assert not governor._is_halted()

    def test_is_halted_false_when_no_file(self):
        assert not governor._is_halted()

    def test_stale_halt_file_logs_warning(self, caplog):
        # Create a halt file with old timestamp
        path = governor._get_halt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        old_time = (datetime.now(ET) - timedelta(hours=49)).isoformat()
        path.write_text(json.dumps({"halted_at": old_time, "source": "test"}))

        import logging
        with caplog.at_level(logging.WARNING):
            result = governor._is_halted()
        assert result is True  # Still honors stale halt
        assert "stale" in caplog.text.lower() or "48" in caplog.text

    def test_halt_info_returns_metadata(self):
        governor._global_halt(True, source="telegram", reason="manual halt")
        info = governor._halt_info()
        assert info is not None
        assert info["source"] == "telegram"
        assert info["reason"] == "manual halt"

    def test_halt_info_none_when_not_halted(self):
        assert governor._halt_info() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_kill_switch.py -v`
Expected: TypeError — `_global_halt()` doesn't accept `source`/`reason` kwargs

- [ ] **Step 3: Implement atomic kill switch**

Replace `_global_halt`, `_is_halted` in `src/risk/governor.py`:

```python
import json
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def _global_halt(halt: bool, source: str = "unknown", reason: str = ""):
    """Set or clear the global trading halt atomically.

    Uses atomic file rename (os.replace) so the halt file is never
    partially written. Writes JSON with timestamp for staleness checks.
    """
    halt_path = _get_halt_path()
    if halt:
        halt_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "halted_at": datetime.now(_ET).isoformat(),
            "source": source,
            "reason": reason,
        }
        tmp_path = str(halt_path) + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, str(halt_path))
        logger.warning("[RISK] Trading HALTED by %s: %s", source, reason)
        _log_halt_event("halt", source, reason)
    else:
        if halt_path.exists():
            halt_path.unlink(missing_ok=True)
        logger.warning("[RISK] Trading RESUMED")
        _log_halt_event("resume", source, reason)


def _is_halted() -> bool:
    """Check if trading is globally halted. Warns if halt file is stale (>48h)."""
    halt_path = _get_halt_path()
    if not halt_path.exists():
        return False
    try:
        data = json.loads(halt_path.read_text())
        halted_at = datetime.fromisoformat(data["halted_at"])
        age_hours = (datetime.now(_ET) - halted_at).total_seconds() / 3600
        if age_hours > 48:
            logger.warning(
                "[RISK] Stale halt file detected (%.0fh old) — still honoring halt. "
                "Resume trading explicitly if this is unintended.", age_hours
            )
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.warning("[RISK] Halt file exists but unreadable — honoring halt")
    return True


def _halt_info() -> dict | None:
    """Return halt metadata (timestamp, source, reason) or None if not halted."""
    halt_path = _get_halt_path()
    if not halt_path.exists():
        return None
    try:
        return json.loads(halt_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {"halted_at": "unknown", "source": "unknown", "reason": ""}


def _log_halt_event(event_type: str, source: str, reason: str):
    """Log halt/resume to activity_log for audit trail."""
    try:
        from src.utils.activity_logger import log_activity
        log_activity(
            f"kill_switch_{event_type}",
            f"source={source}, reason={reason}",
        )
    except Exception as exc:
        logger.warning("[RISK] Failed to log halt event: %s", exc)
```

- [ ] **Step 4: Update existing callers**

Search for any calls to `_global_halt(True)` or `_global_halt(False)` in the codebase and add `source=` kwarg where appropriate:

- `src/cli/commands.py` — `_global_halt(True, source="cli", reason="halt-trading command")`
- `src/api/routes/actions.py` — `_global_halt(True, source="dashboard", reason="dashboard halt button")`
- `src/notifications/telegram.py` — `_global_halt(True, source="telegram", reason="telegram /halt command")`

Existing calls without `source=` will default to `"unknown"` which is safe.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_kill_switch.py tests/test_governor.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/risk/governor.py tests/test_kill_switch.py
git commit -m "fix: atomic kill switch with staleness check + audit trail (#106)"
```

---

### Task 6: Final verification + close issues

**Files:**
- Modify: `MASTER.md` (update open issues list)

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -q --tb=short
```
Expected: >= 1105 tests, no regressions

- [ ] **Step 2: Run migration script for failed trades**

```bash
python scripts/mark_failed_trades.py --dry-run
python scripts/mark_failed_trades.py
```

- [ ] **Step 3: Verify schema**

```bash
python -m src.main validate-schema
```

- [ ] **Step 4: Update MASTER.md**

Remove #188, #187, #147, #132, #106 from the open issues table. Update issue count.

- [ ] **Step 5: Commit docs update**

```bash
git add MASTER.md
git commit -m "docs: update MASTER.md — close remaining 5 issues"
```

- [ ] **Step 6: Push, create PR, close issues**

```bash
git push origin <branch>
gh pr create --title "fix: comprehensive hardening — 5 remaining issues" --body "..."
gh pr merge <number> --merge
gh issue close 188 187 147 132 106
```
