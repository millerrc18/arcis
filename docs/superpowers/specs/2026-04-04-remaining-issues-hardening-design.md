# Remaining Issues Hardening — Design Spec

**Date:** 2026-04-04
**Issues:** #188, #187, #147, #132, #106
**Scope:** Comprehensive hardening — fixes, guardrails, tests, docs

---

## Context

After the automated audit rectification (PR #210) and bulk issue cleanup, 5 issues remain open. These are systemic reliability gaps — not one-off bugs — each requiring defensive infrastructure alongside the direct fix.

---

## Issue #188 — Negative shares in long-only system

**Root cause:** `reconcile.py:_backfill_trade_data()` accepts `qty` directly from Alpaca position data without validating `qty > 0`. Short positions (e.g., PFE with -14 shares) get inserted as trades.

### Changes

**`src/shadow_trading/reconcile.py`**
- `_backfill_trade_data()` (line 24): Return `None` if `qty <= 0`, log warning
- Live backfill caller (line 100-113): Skip if backfill returns None
- Paper backfill caller (line 259-271): Skip if backfill returns None

**`src/schema/registry.py`**
- Add `check="planned_shares > 0"` to the `planned_shares` ColumnDef
- Add `check="actual_shares > 0"` to the `actual_shares` ColumnDef (if supported by the ColumnDef dataclass — verify first)

**`tests/test_reconcile.py`**
- Test: negative qty returns None from `_backfill_trade_data()`
- Test: zero qty returns None
- Test: positive qty returns valid trade dict

---

## Issue #187 — Failed trades, insufficient buying power

**Root cause:** Paper entry path has no buying power validation. Failed trades with `status="failed"` accumulate but are never retried (confirmed by code review — the issue title is slightly misleading). The real problem is 44 trades that failed on first attempt due to insufficient buying power and now clutter monitoring.

### Changes

**`src/shadow_trading/executor.py`**
- Add buying power check before paper order placement (mirror the live path at lines 1029-1038)
- In the paper entry flow, fetch account balance and validate `buying_power >= entry_price * shares` before calling `place_paper_entry()` or `place_bracket_order()`

**Data migration (one-time script or inline)**
- `UPDATE shadow_trades SET status='failed_permanent' WHERE status='failed'`
- This prevents them from appearing in active monitoring queries
- Add `failed_permanent` to the status enum documentation

**`tests/test_executor_import.py` or new test file**
- Test: paper entry rejected when buying power insufficient
- Test: `failed_permanent` status is treated as terminal (not retried, not monitored)

---

## Issue #147 — No exponential backoff in enrichment

**Root cause:** All enrichment and data collection modules use fixed `time.sleep()` delays. Network failures are retried with constant delay or not retried at all.

### Changes

**New file: `src/utils/retry.py`**
```python
def retry_with_backoff(
    fn,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
) -> any:
    """Call fn with exponential backoff on failure."""
```
- Exponential backoff: `delay = min(base_delay * 2^attempt, max_delay)`
- Add jitter (±20%) to prevent thundering herd
- Log each retry at WARNING level
- Return None (or raise) after max retries exhausted

**Apply to enrichment modules:**
- `src/data_enrichment/news.py` — wrap Finnhub/news API calls
- `src/data_enrichment/insiders.py` — wrap Finnhub insider API calls
- `src/data_enrichment/fundamentals.py` — wrap API calls
- `src/data_enrichment/macro.py` — wrap FRED API calls

**Apply to collection modules (highest-impact):**
- `src/data_collection/analyst_collector.py`
- `src/data_collection/insider_collector.py`
- `src/data_collection/short_interest_collector.py`

**`tests/test_retry.py`**
- Test: succeeds on first try (no delay)
- Test: retries N times then returns None
- Test: exponential delay increases
- Test: jitter applied

---

## Issue #132 — Placeholder config keys accepted silently

**Root cause:** `config/__init__.py:load_config()` loads settings files without validating that API keys are real values vs placeholder strings from `settings.example.yaml`.

### Changes

**`src/config/__init__.py`**
- Add `validate_config(config: dict) -> list[str]` function
- Check critical keys against placeholder patterns:
  - Regex: `r"^your[-_]|placeholder|example|YOUR_|^$"`
  - Keys to check: `alpaca.api_key`, `alpaca.secret_key`, `finnhub.api_key`, `fred.api_key`, `anthropic.api_key`, `telegram.bot_token`
- Return list of warning messages (key name, not value)
- Call `validate_config()` at end of `load_config()`, log each warning at WARNING level
- If loading `settings.example.yaml` (not `.local.yaml`), log a prominent WARNING: "Using example config — API keys are placeholders"

**Integration:**
- `src/main.py` — call `validate_config()` during startup / preflight
- Don't crash — log warnings only (devs may intentionally use partial config)

**`tests/test_config_validation.py`**
- Test: placeholder values detected
- Test: real values pass validation
- Test: missing keys handled gracefully
- Test: warning logged when using example config

---

## Issue #106 — Kill switch not atomic

**Root cause:** `governor.py:_global_halt()` uses `Path.touch()` and `Path.unlink()` — non-atomic file operations with no timestamp validation or audit trail.

### Changes

**`src/risk/governor.py`**
- `_global_halt(halt=True)`: Write timestamp JSON to temp file, then `os.replace(temp, halt_path)` (atomic on both Windows/POSIX)
- `_global_halt(halt=False)`: `os.replace(halt_path, halt_path + ".removed")` then delete (atomic removal)
- `_is_halted()`: Check file exists AND parse timestamp from contents. If timestamp > 48h old, log WARNING about potentially stale halt file (but still honor it)
- Add `_halt_info() -> dict | None` to return halt metadata (timestamp, source)
- Log halt/resume events to `activity_log` table for audit trail

**Halt file format:**
```json
{"halted_at": "2026-04-04T21:00:00-04:00", "source": "telegram", "reason": "manual halt"}
```

**`tests/test_governor.py`**
- Test: atomic creation (file exists after halt)
- Test: atomic removal (file gone after resume)
- Test: stale halt file detected (>48h)
- Test: concurrent halt/resume (no corruption)
- Test: activity_log entry created on halt/resume

---

## Verification

After all changes:
```bash
# Full test suite — must stay above 1105
python -m pytest tests/ -q

# Schema validation
python -m src.main validate-schema --fix

# Verify retry utility works
python -m pytest tests/test_retry.py -v

# Config validation
python -c "from src.config import load_config, validate_config; print(validate_config(load_config()))"

# Kill switch round-trip
python -c "from src.risk.governor import _global_halt, _is_halted; _global_halt(True); print(_is_halted()); _global_halt(False); print(_is_halted())"

# Verify no failed trades retrying
python -c "import sqlite3; c=sqlite3.connect('data/arcis.db'); print(c.execute('SELECT count(*) FROM shadow_trades WHERE status=?', ('failed',)).fetchone())"
```
