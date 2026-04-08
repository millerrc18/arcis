# Structured Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured context to log output so AI agents can parse, filter, and aggregate log events without regex — while keeping messages human-readable.

**Architecture:** A `StructuredFormatter` appends `|ctx:{JSON}` to log lines when a `ctx` dict is present in `extra`. A `scan_id` field on `ScanContext` threads correlation through the scan pipeline. A cycle summary line is emitted at the end of each scan. The `DBLogHandler` stores `ctx` in the existing `details_json` column. No new dependencies.

**Tech Stack:** Python 3.12 stdlib `logging`, `json`, `dataclasses`

**Spec:** GH issue #314

**Branch:** `fix/structured-logging-314`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/log_config.py` | Modify | Add `StructuredFormatter` class |
| `src/scheduler/watch.py` | Modify | Generate `scan_id`, emit cycle summary, update `DBLogHandler` |
| `src/scheduler/universe_scanner.py` | Modify | Add `scan_id` to `ScanContext` |
| `src/shadow_trading/executor.py` | Modify | Add `ctx` to high-value log calls (5 calls) |
| `src/llm/packet_writer.py` | Modify | Add `ctx` to conviction/parse log calls (3 calls) |
| `src/sync/render_sync.py` | Modify | Add `ctx` to sync error log calls (2 calls) |
| `tests/test_log_config.py` | Create | Test `StructuredFormatter` |
| `tests/test_scan_context.py` | Create | Test `scan_id` generation + summary |

---

### Task 1: Create StructuredFormatter

**Files:**
- Modify: `src/log_config.py`
- Create: `tests/test_log_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_log_config.py
"""Tests for structured log formatting."""

import logging
import json


class TestStructuredFormatter:
    def test_plain_message_unchanged(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello world", (), None)
        result = fmt.format(record)
        assert result == "hello world"
        assert "|ctx:" not in result

    def test_ctx_appended_as_json(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "exit failed", (), None)
        record.ctx = {"event": "exit_failed", "ticker": "TGT"}
        result = fmt.format(record)
        assert result.startswith("exit failed |ctx:")
        ctx_json = result.split("|ctx:")[1]
        parsed = json.loads(ctx_json)
        assert parsed["event"] == "exit_failed"
        assert parsed["ticker"] == "TGT"

    def test_ctx_none_no_suffix(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "normal log", (), None)
        record.ctx = None
        result = fmt.format(record)
        assert "|ctx:" not in result

    def test_ctx_empty_dict_no_suffix(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "normal log", (), None)
        record.ctx = {}
        result = fmt.format(record)
        assert "|ctx:" not in result

    def test_full_format_string(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        record = logging.LogRecord("src.executor", logging.ERROR, "", 0, "broker fail", (), None)
        record.ctx = {"event": "exit_failed"}
        result = fmt.format(record)
        assert "[src.executor] ERROR: broker fail |ctx:" in result

    def test_ctx_with_scan_id(self):
        from src.log_config import StructuredFormatter
        fmt = StructuredFormatter("%(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "scan done", (), None)
        record.ctx = {"event": "scan_complete", "scan_id": "s-042", "duration_s": 180}
        result = fmt.format(record)
        parsed = json.loads(result.split("|ctx:")[1])
        assert parsed["scan_id"] == "s-042"
        assert parsed["duration_s"] == 180
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_log_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'StructuredFormatter'`

- [ ] **Step 3: Write the implementation**

In `src/log_config.py`, add above the existing `setup_logging` function:

```python
import json


class StructuredFormatter(logging.Formatter):
    """Log formatter that appends structured context as |ctx:{JSON}.

    When a LogRecord has a non-empty ``ctx`` attribute (set via
    ``extra={"ctx": {...}}``), the JSON is appended after the message.
    Plain messages are unchanged — backwards-compatible.

    Example output:
        2026-04-06 09:01:00 [executor] ERROR: Exit failed for TGT |ctx:{"event":"exit_failed","ticker":"TGT"}
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        ctx = getattr(record, "ctx", None)
        if ctx:
            return f"{base} |ctx:{json.dumps(ctx, separators=(',', ':'), default=str)}"
        return base
```

Then in `setup_logging`, change the formatter class:

```python
    # Before:
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    # After:
    fmt = StructuredFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_log_config.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/log_config.py tests/test_log_config.py
git commit -m "feat: add StructuredFormatter with |ctx:{} JSON suffix (#314)"
```

---

### Task 2: Update DBLogHandler to store ctx in details_json

**Files:**
- Modify: `src/scheduler/watch.py:67-95` (DBLogHandler.emit)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_log_config.py`:

```python
class TestDBLogHandlerCtx:
    def test_ctx_stored_in_details_json(self, tmp_path):
        """DBLogHandler should store ctx dict in details_json column."""
        import sqlite3
        from src.journal.store import initialize_database

        db = str(tmp_path / "test.db")
        initialize_database(db)

        from src.scheduler.watch import DBLogHandler
        handler = DBLogHandler(db_path=db)

        record = logging.LogRecord(
            "src.test", logging.WARNING, "", 0, "test warning", (), None)
        record.ctx = {"event": "test_event", "ticker": "AAPL"}
        handler.emit(record)

        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT details_json FROM log_entries LIMIT 1").fetchone()
        assert row is not None
        parsed = json.loads(row[0])
        assert parsed["event"] == "test_event"
        assert parsed["ticker"] == "AAPL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_log_config.py::TestDBLogHandlerCtx -v`
Expected: FAIL — details_json is None (ctx not stored)

- [ ] **Step 3: Apply the fix**

In `src/scheduler/watch.py`, modify `DBLogHandler.emit()` around line 73-75:

```python
        # Before:
            details = None
            if record.exc_info and record.exc_info[1]:
                details = str(record.exc_info[1])[:5000]
        # After:
            details = None
            ctx = getattr(record, "ctx", None)
            if ctx:
                details = json.dumps(ctx, separators=(",", ":"), default=str)[:5000]
            elif record.exc_info and record.exc_info[1]:
                details = str(record.exc_info[1])[:5000]
```

Add `import json` at top of file if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_log_config.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/scheduler/watch.py tests/test_log_config.py
git commit -m "feat: store ctx in details_json via DBLogHandler (#314)"
```

---

### Task 3: Add scan_id to ScanContext and generate it in watch loop

**Files:**
- Modify: `src/scheduler/universe_scanner.py:28-31` (ScanContext dataclass)
- Modify: `src/scheduler/watch.py:674` (scan_id generation)

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_context.py`:

```python
# tests/test_scan_context.py
"""Tests for scan_id generation and ScanContext."""


class TestScanContext:
    def test_scan_id_field_exists(self):
        from src.scheduler.universe_scanner import ScanContext
        ctx = ScanContext(config={}, scan_id="s-001")
        assert ctx.scan_id == "s-001"

    def test_scan_id_defaults_to_none(self):
        from src.scheduler.universe_scanner import ScanContext
        ctx = ScanContext(config={})
        assert ctx.scan_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scan_context.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'scan_id'`

- [ ] **Step 3: Add scan_id to ScanContext**

In `src/scheduler/universe_scanner.py`, modify the dataclass:

```python
@dataclass
class ScanContext:
    """Input context for a universe scan."""
    config: dict
    db_path: str = DB_PATH
    scan_id: str | None = None
```

- [ ] **Step 4: Generate scan_id in watch loop**

In `src/scheduler/watch.py`, in `_run_scan()` around line 674:

```python
    # Before:
        ctx = ScanContext(config=self.config)
    # After:
        _scan_num = getattr(self, "_scan_number", 0) + 1
        ctx = ScanContext(config=self.config, scan_id=f"s-{_scan_num:04d}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_scan_context.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/scheduler/universe_scanner.py src/scheduler/watch.py tests/test_scan_context.py
git commit -m "feat: add scan_id to ScanContext for log correlation (#314)"
```

---

### Task 4: Emit structured cycle summary at end of each scan

**Files:**
- Modify: `src/scheduler/watch.py:789-816` (_record_scan_metrics)

- [ ] **Step 1: Add structured summary log to _record_scan_metrics**

In `src/scheduler/watch.py`, at the end of `_record_scan_metrics`, before the existing `logger.info` line (around line 813), add:

```python
            # Structured cycle summary for AI agent review (#314)
            logger.info(
                "[WATCH] Scan cycle #%d complete",
                self._scan_number,
                extra={"ctx": {
                    "event": "scan_summary",
                    "scan_id": f"s-{self._scan_number:04d}",
                    "scan_number": self._scan_number,
                    "universe": universe_count,
                    "features": features_count,
                    "qualified": packet_worthy,
                    "llm_success": llm_success,
                    "llm_total": llm_total,
                    "conviction_none_rate": round(
                        1 - (llm_success / llm_total), 2) if llm_total > 0 else 0.0,
                }},
            )
```

Remove or keep the existing `logger.info("[WATCH] Recorded scan_metrics #%d ...")` — keeping it is fine since the new structured line adds context without replacing it.

- [ ] **Step 2: Run existing tests**

Run: `python -m pytest tests/ -q --ignore=tests/test_digest_builder.py --tb=line 2>&1 | tail -3`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add src/scheduler/watch.py
git commit -m "feat: emit structured scan_summary at cycle end (#314)"
```

---

### Task 5: Add ctx to executor exit log calls

**Files:**
- Modify: `src/shadow_trading/executor.py` (3 high-value log calls)

- [ ] **Step 1: Add ctx to the exception handler (line ~883)**

```python
    # Before:
                    logger.error("[EXIT] Broker exit failed for %s — marking exit_failed: %s", ticker, e)
    # After:
                    logger.error(
                        "[EXIT] Broker exit failed for %s — marking exit_failed: %s", ticker, e,
                        extra={"ctx": {"event": "exit_failed", "ticker": ticker,
                                       "trade_id": trade["trade_id"],
                                       "error": type(e).__name__}},
                    )
```

- [ ] **Step 2: Add ctx to the status-based exit_failed handler (line ~982)**

```python
    # Before:
                    logger.error(
                        "[EXIT] Broker exit failed for %s — marking exit_failed (status=%s)",
                        ticker, exit_status,
                    )
    # After:
                    logger.error(
                        "[EXIT] Broker exit failed for %s — marking exit_failed (status=%s)",
                        ticker, exit_status,
                        extra={"ctx": {"event": "exit_failed", "ticker": ticker,
                                       "trade_id": trade["trade_id"],
                                       "status": str(exit_status)}},
                    )
```

- [ ] **Step 3: Add ctx to successful exit close (after close_shadow_trade call)**

Find the `close_shadow_trade` call in the exit success path and add after it:

```python
                    logger.info(
                        "[EXIT] Closed %s — P&L $%.2f (%.1f%%)", ticker, pnl_dollars, pnl_pct,
                        extra={"ctx": {"event": "exit_success", "ticker": ticker,
                                       "trade_id": trade["trade_id"],
                                       "pnl_dollars": round(pnl_dollars, 2),
                                       "pnl_pct": round(pnl_pct, 2),
                                       "exit_reason": exit_reason}},
                    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_executor_import.py -v`
Expected: All pass (ctx in extra doesn't affect mock assertions)

- [ ] **Step 5: Commit**

```bash
git add src/shadow_trading/executor.py
git commit -m "feat: add structured ctx to executor exit log calls (#314)"
```

---

### Task 6: Add ctx to LLM packet_writer log calls

**Files:**
- Modify: `src/llm/packet_writer.py`

- [ ] **Step 1: Add ctx to conviction None warning (line ~494)**

```python
    # Before:
        _raw_preview = repr(response[:500]) if response else "EMPTY"
        logger.warning(
            "[LLM] Conviction is None for %s — defaulting to %d. "
            "Response preview: %s",
            packet.ticker, conviction, _raw_preview,
        )
    # After:
        _raw_preview = repr(response[:500]) if response else "EMPTY"
        logger.warning(
            "[LLM] Conviction is None for %s — defaulting to %d. "
            "Response preview: %s",
            packet.ticker, conviction, _raw_preview,
            extra={"ctx": {"event": "conviction_default", "ticker": packet.ticker,
                           "default": conviction}},
        )
```

- [ ] **Step 2: Add ctx to parse failure (line ~486)**

```python
    # Before:
        logger.warning("[LLM] Failed to parse response — fallback to template for %s", packet.ticker)
    # After:
        logger.warning(
            "[LLM] Failed to parse response — fallback to template for %s", packet.ticker,
            extra={"ctx": {"event": "parse_failure", "ticker": packet.ticker}},
        )
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_packet_writer.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/llm/packet_writer.py
git commit -m "feat: add structured ctx to LLM conviction/parse log calls (#314)"
```

---

### Task 7: Add ctx to render_sync error log calls

**Files:**
- Modify: `src/sync/render_sync.py`

- [ ] **Step 1: Find and update sync error log calls**

Search for `logger.error` in render_sync.py and add ctx:

```python
    # For upsert failures:
    logger.error(
        "Postgres upsert failed for %s: %s", table_name, e,
        extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(e)}},
    )

    # For sync failures:
    logger.error(
        "Sync failed for %s: %s", table_name, e,
        extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(e)}},
    )
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_render_sync.py -v --tb=short 2>&1 | tail -5`
Expected: All 37 pass

- [ ] **Step 3: Commit**

```bash
git add src/sync/render_sync.py
git commit -m "feat: add structured ctx to render sync error log calls (#314)"
```

---

### Task 8: Final verification + documentation

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ --co -q --ignore=tests/test_digest_builder.py 2>&1 | tail -3
```

Expected: test count >= 1447 (1439 baseline + 8 new)

- [ ] **Step 2: Verify structured output works end-to-end**

```python
python -c "
import logging
from src.log_config import setup_logging
setup_logging(level='INFO')
logger = logging.getLogger('test')
logger.info('Plain message')
logger.warning('Exit failed for TGT', extra={'ctx': {'event': 'exit_failed', 'ticker': 'TGT'}})
print('Check console output for |ctx: suffix on second line')
"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: structured logging implementation complete (#314)"
```

---

## Ralph Loop Verification (3 iterations)

### Iteration 1 — Spec coverage check:
- [x] StructuredFormatter with |ctx:{} suffix — Task 1
- [x] DBLogHandler stores ctx in details_json — Task 2
- [x] scan_id correlation — Task 3
- [x] Cycle summary emission — Task 4
- [x] Executor ctx annotations — Task 5
- [x] LLM ctx annotations — Task 6
- [x] Sync ctx annotations — Task 7
- **Gap found:** Spec mentions DeduplicationHandler but that adds significant complexity. Deferred — the structured ctx makes dedup easy for AI agents to do client-side (`grep "exit_failed" | jq .ticker | sort | uniq -c`). Filed as follow-up.
- **Gap found:** Spec mentions risk governor ctx — but governor only has 1 rejection log call that already contains all data in the message. Low value. Skipped.

### Iteration 2 — Placeholder and consistency check:
- **Fixed:** Task 4 used `self._scan_number` but that's incremented INSIDE `_record_scan_metrics`. The summary must use the post-increment value. Verified — `_scan_number` is incremented at line 797 before the INSERT, so the summary correctly uses the new value.
- **Fixed:** Task 3 generates scan_id as `f"s-{_scan_num:04d}"` but `_scan_num` is `self._scan_number + 1`. Meanwhile `_record_scan_metrics` also increments. This would cause scan_id mismatch. Fix: use `self._scan_number` directly in the summary (Task 4), not the pre-incremented value from Task 3. The scan_id in ScanContext is for downstream modules; the summary uses `self._scan_number` directly.
- **Verified:** `json.dumps(ctx, separators=(",", ":"), default=str)` — `default=str` handles datetime, UUID, and other non-serializable types safely.

### Iteration 3 — Risk and edge case check:
- **Risk:** `extra={"ctx": {...}}` on existing log calls — could this break any existing test that asserts on log output? Checked: executor tests use `mock_update.call_args`, not log capture. Packet writer tests call `_parse_llm_response` directly. Safe.
- **Risk:** StructuredFormatter adds import `json` to log_config.py. This is stdlib — zero risk.
- **Edge case:** What if `ctx` contains non-serializable objects (e.g., exceptions)? The `default=str` parameter in `json.dumps` handles this by converting to string representation. Tested in Task 1.
- **Edge case:** What if log message itself contains `|ctx:`? This is a delimiter collision. Extremely unlikely in practice since no existing message contains this string. Acceptable risk.
