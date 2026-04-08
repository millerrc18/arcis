# Sprint 5: Codebase Refactor Baseline — Design Spec

> **Branch:** `refactor/codebase-baseline`
> **Priority:** MEDIUM
> **Estimated CC time:** 3-4 hours
> **Rule:** Never refactor and add features in the same sprint.
> **Author:** Claude (CTO), Ralph looped 3×

---

## Problem

Two files violate the 400-line rule by a combined 4,166 lines:

| File | Current | Limit | Over by |
|------|---------|-------|---------|
| `src/scheduler/watch.py` | 3,403 | 400 | 3,003 |
| `src/notifications/telegram.py` | 1,563 | 400 | 1,163 |

Both are grandfathered in `config/known_violations.json`, but they're the
#1 and #2 maintainability risks in the codebase. Every CC sprint that touches
scheduling or notifications risks merge conflicts, and the function count in
each file makes comprehension difficult.

---

## Design

### Extraction pattern

All extracted functions become **standalone module-level functions** that
accept explicit parameters (`config`, `db_path`, etc.) instead of `self`.
The WatchLoop class retains **thin proxy methods** that delegate:

```python
# BEFORE (in watch.py, 210 lines of logic):
def _run_data_collection(self):
    """12 overnight collectors..."""
    # 210 lines of collection logic

# AFTER (in watch.py, 3 lines):
def _run_data_collection(self):
    from src.scheduler.overnight import run_data_collection
    run_data_collection(self.config, self.db_path)
```

This pattern ensures:
- Zero import changes needed anywhere else in the codebase
- The WatchLoop remains the orchestrator; new modules contain pure logic
- Each function is independently testable without WatchLoop instantiation

---

## File 1: watch.py (3,403 → ~1,793 lines)

### Extract → `src/scheduler/overnight.py` (~919 lines, 23 functions)

Post-close, overnight, and pre-market task logic. Every function currently
on `self` becomes a standalone function taking `config` and `db_path`.

| Function | Lines | What it does |
|----------|-------|-------------|
| `run_eod_recap` | 47 | End-of-day P&L summary |
| `run_postclose_reconciliation` | 46 | Stale position cleanup |
| `run_daily_audit` | 56 | Schema + integrity checks |
| `run_training_collection` | 7 | Export closed trades as training data |
| `run_training_check` | 25 | Trigger retrain if threshold exceeded |
| `run_saturday_reports` | 82 | Weekly CTO report + digest |
| `log_overnight_task` | 15 | Write task status to activity_log |
| `run_model_regression_check` | 23 | Canary eval on current model |
| `run_post_close_capture` | 69 | Snapshot positions + features at close |
| `run_overnight_training_collection` | 36 | Training generation batch |
| `run_news_ingestion` | 33 | Pull overnight news + score |
| `run_enrichment_precache` | 32 | Pre-compute features for next open |
| `run_pre_market_refresh` | 28 | OHLCV + fundamentals update |
| `run_data_collection` | 210 | 12 overnight collectors (largest function) |
| `run_evening_handoff` | 33 | VRAM handoff GPU → training mode |
| `run_morning_handoff` | 40 | VRAM handoff training → inference mode |
| `run_daily_council` | 43 | AI Council session |
| `run_ollama_warmup` | 46 | CUDA kernel warmup before first scan |
| `run_premarket_rolling_features` | 7 | Rolling feature computation |
| `run_premarket_training` | 11 | Pre-market training data gen |
| `run_premarket_news_scoring` | 7 | FinBERT scoring on overnight news |
| `run_premarket_candidates` | 7 | Pre-screen universe for watchlist |
| `run_stress_test` | 16 | Sunday night stress test run |

**Function signature pattern:**
```python
def run_data_collection(config: dict, db_path: str = DB_PATH,
                         logger_fn=None) -> dict:
    """Run all 12 overnight data collectors.
    
    Returns: dict with collector names -> status/error.
    """
```

**The `logger_fn` parameter** is optional — if not provided, functions use
the module-level logger. This avoids needing to pass the WatchLoop's
`_log_overnight_task` method as a dependency.

### Extract → `src/scheduler/reports.py` (~691 lines, 8 functions)

Report generation and digest formatting. These functions assemble data
and call `send_telegram` / `notify_*` — they're pure report logic.

| Function | Lines | What it does |
|----------|-------|-------------|
| `send_premarket_brief` | 125 | Morning brief with VIX, regime, movers |
| `send_eod_report` | 114 | EOD email/telegram with P&L, positions |
| `send_data_asset_report` | 53 | Training data asset status |
| `check_vix_regime_alert` | 57 | VIX threshold alerts |
| `send_weekly_digest` | 162 | Full weekly digest with charts |
| `check_earnings_proximity` | 51 | Warn on holdings near earnings |
| `run_morning_watchlist` | 61 | Rank universe, send top picks |
| `save_daily_metric_snapshot` | 68 | Write daily metrics to DB |

**Function signature pattern:**
```python
def send_eod_report(config: dict, db_path: str = DB_PATH) -> bool:
    """Generate and send end-of-day report via Telegram.
    
    Returns: True if sent successfully.
    """
```

### What stays in watch.py (~1,793 lines)

- `WatchLoop` class definition + `__init__` (141 lines)
- Core scheduling: `run()`, `_reset_daily_state`, `_is_market_open`,
  `_should_scan`, `_check_digest_schedule`, `_minutes_until_next_scan`
- Market-hours: `_run_scan`, `_run_mr_scan`, `_post_scan_notifications`,
  `_record_scan_metrics`
- Infrastructure: `_safe_run`, `_acquire_lock`, `_release_lock`,
  `_is_pid_alive`, `_backup_database`, `_ensure_all_tables`,
  `_configure_database`, `_check_row_counts`
- Display: `_get_live_stats`, `_print_banner`, `_print_status_heartbeat`
- Bracket health: `_run_bracket_health_check`
- Thin proxy methods (23 + 8 = 31 methods, ~3 lines each = ~93 lines)
- The main event loop body inside `run()` (~600 lines)

**1,793 lines is still over 400** but represents a 47% reduction and is the
practical limit for this sprint. The remaining bulk is the event loop (600
lines of scheduling `if/elif` branches) which requires an architectural
change (event-driven scheduler) that's a separate sprint.

---

## File 2: telegram.py (1,563 → ~785 lines)

### Extract → `src/notifications/telegram_commands.py` (~778 lines, 19 functions)

The Telegram bot command handler and all `/command` implementations.

| Function | Lines | What it does |
|----------|-------|-------------|
| `poll_commands` | 55 | Long-poll Telegram for bot commands |
| `check_action_reminders` | 139 | Check DB for pending action items |
| `handle_command` | 76 | Route `/command` to handler |
| `_cmd_status` | 32 | System status summary |
| `_cmd_trades` | 60 | Open trades list |
| `_cmd_pnl` | 68 | P&L breakdown |
| `_cmd_last_scan` | 24 | Last scan timestamp + result |
| `_cmd_earnings` | 21 | Upcoming earnings for holdings |
| `_cmd_schedule` | 24 | Next scheduled tasks |
| `_cmd_scoring` | 24 | Training scoring backlog |
| `_cmd_council` | 74 | Run ad-hoc council session |
| `_cmd_health` | 22 | System health checks |
| `_cmd_log` | 26 | Recent log entries |
| `_cmd_pull` | 13 | Git pull from remote |
| `_cmd_logs` | 16 | Tail log file |
| `_cmd_gpu` | 15 | GPU utilization |
| `_cmd_disk` | 31 | Disk usage |
| `_cmd_uptime` | 29 | System uptime |
| `_cmd_heartbeat` | 29 | Heartbeat file status |

### What stays in telegram.py (~785 lines)

- Core: `_get_telegram_config`, `is_telegram_enabled`, `send_telegram`
- All 28 `notify_*` functions (imported by 11 other files)
- `notify_action_required`
- `notify_validation_summary`

**Import compatibility:** The only files importing command functions are:
- `watch.py` line 1480: `from src.notifications.telegram import check_action_reminders`
- `watch.py`'s event loop: `poll_commands`, `handle_command`

These 3 call sites need to be updated to import from
`src.notifications.telegram_commands` instead. All other files only import
`notify_*` and `send_telegram` — zero changes needed.

---

## Backward compatibility

### Re-export guard (optional but recommended)

Add to bottom of `telegram.py`:
```python
# Backward compatibility — remove after all callers are updated
try:
    from src.notifications.telegram_commands import (
        poll_commands, handle_command, check_action_reminders
    )
except ImportError:
    pass
```

This prevents breakage if any caller hasn't been updated yet. Can be removed
after one full release cycle.

---

## Test plan

### New tests required:

1. `test_overnight_imports` — all 23 functions importable from `src.scheduler.overnight`
2. `test_reports_imports` — all 8 functions importable from `src.scheduler.reports`
3. `test_telegram_commands_imports` — all 19 functions importable from `src.notifications.telegram_commands`
4. `test_proxy_delegation` — WatchLoop proxy methods call the extracted function (mock + verify)
5. `test_existing_tests_pass` — full `pytest` suite passes with zero regressions

### Existing test verification:

```bash
# Before extraction: record baseline
pytest --tb=short -q 2>&1 | tail -5 > /tmp/before.txt

# After extraction: compare
pytest --tb=short -q 2>&1 | tail -5 > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt
```

---

## Migration checklist (for CC)

### Pre-flight:
- [ ] `git checkout -b refactor/codebase-baseline`
- [ ] `pytest --tb=short -q` passes (record pass count)
- [ ] Verify `wc -l src/scheduler/watch.py` = 3,403
- [ ] Verify `wc -l src/notifications/telegram.py` = 1,563

### Step 1: Create overnight.py
- [ ] Create `src/scheduler/overnight.py` with module docstring
- [ ] Extract 23 functions, converting `self.config` → `config` parameter
- [ ] Add `from src.scheduler.watch import DB_PATH` or accept as param
- [ ] Each function gets its own logger: `logger = logging.getLogger(__name__)`
- [ ] Replace each watch.py method body with 3-line proxy

### Step 2: Create reports.py
- [ ] Create `src/scheduler/reports.py` with module docstring
- [ ] Extract 8 functions, same parameter pattern
- [ ] Replace each watch.py method body with 3-line proxy

### Step 3: Create telegram_commands.py
- [ ] Create `src/notifications/telegram_commands.py`
- [ ] Move 19 functions (poll_commands, handle_command, check_action_reminders, all _cmd_*)
- [ ] Add `from src.notifications.telegram import send_telegram, is_telegram_enabled`
- [ ] Update 3 import sites in watch.py
- [ ] Add re-export guard in telegram.py

### Step 4: Verify
- [ ] `pytest --tb=short -q` — same pass count as pre-flight
- [ ] `wc -l src/scheduler/watch.py` ≈ 1,793
- [ ] `wc -l src/notifications/telegram.py` ≈ 785
- [ ] `wc -l src/scheduler/overnight.py` ≈ 919
- [ ] `wc -l src/scheduler/reports.py` ≈ 691
- [ ] `wc -l src/notifications/telegram_commands.py` ≈ 778
- [ ] No file in `src/` over 400 lines except watch.py (grandfathered at ~1,793)
- [ ] `grep -rn "from src.notifications.telegram import" src/ | grep -v __pycache__` — verify no broken imports
- [ ] Frontend build: `cd frontend && npm run build`

### Step 5: Commit
- [ ] `git add -A && git commit -m "refactor: Sprint 5 — codebase refactor baseline

Extract 1,610 lines from watch.py into overnight.py + reports.py.
Extract 778 lines from telegram.py into telegram_commands.py.

watch.py:   3,403 -> ~1,793 lines (47% reduction)
telegram.py: 1,563 -> ~785 lines (50% reduction)

Zero behavioral changes. All existing tests pass.
Proxy pattern: WatchLoop methods delegate to standalone functions."`

---

## Known limitations

1. **watch.py still over 400 lines (~1,793):** The remaining bulk is the
   600-line event loop (`run()` method) which is scheduling logic. Extracting
   it requires an event-driven scheduler refactor — a separate sprint.

2. **overnight.py will be ~919 lines:** Acceptable for a module containing
   23 independent task functions. Can be further split into
   `overnight_collectors.py` + `overnight_tasks.py` in a future sprint if needed.

3. **No behavioral changes:** This sprint moves code only. No bug fixes, no
   feature additions, no logic changes. Every function must produce identical
   output before and after extraction.

---

## Ralph Loop

### Iteration 1:
- Initial design extracted overnight + reports from watch.py
- MISSED: telegram.py split. Added telegram_commands.py extraction.
- MISSED: backward compatibility for imports. Added re-export guard.

### Iteration 2:
- Reviewed all 23 overnight functions — verified each accesses only
  `self.config` and `self.db_path` (no other WatchLoop state needed).
  Exception: `_run_data_collection` also accesses `self._last_collection_results`
  for deduplication → solution: pass as parameter or move state to module-level dict.
- Added exact line ranges for every function to enable surgical extraction.
- Added pre-flight line count verification to catch drift.

### Iteration 3:
- Verified import compatibility: only 3 call sites need updating for
  telegram_commands.py (all in watch.py). All 11 files importing notify_*
  are unaffected.
- Added note that watch.py at ~1,793 is the practical limit — the event loop
  refactor is a separate architectural sprint.
- **Critical finding: 4 functions access WatchLoop state beyond config/db_path:**
  - `_run_eod_recap`: reads `self.email_mode`, `self._daily_packets`, `self.LOCKFILE`
    → Pass as params: `email_mode: str`, `daily_packets: list`, `lockfile_dir: Path`
  - `_run_data_collection`: reads/writes `self._collector_failures` (dict)
    → Pass as param: `collector_failures: dict` (mutable, updates in-place)
  - `_run_pre_market_refresh`: same `self._collector_failures`
    → Same pattern as above
  - `_run_evening_handoff`: assigns `self._vram_manager`
    → Return the VRAMManager; proxy sets `self._vram_manager = result`
- **3 report functions also access state:**
  - `_check_vix_regime_alert`, `_send_eod_report`, `_send_data_asset_report`:
    read/write `self._last_vix_alert_level`
    → Pass as param: `last_vix_level: float | None`, return new level.
    Proxy: `self._last_vix_alert_level = result`
  - `_run_morning_watchlist`: reads `self.email_mode`, calls `self._record_scan_metrics`
    → Pass `email_mode: str`. Return metrics dict; proxy calls `_record_scan_metrics`.
- Total: 8 of 31 extracted functions need stateful proxies (~6-8 lines).
  The other 23 are clean — config + db_path only.
- Confirmed `_log_overnight_task` writes to `activity_log` table — the
  extracted version needs `db_path` parameter, not `self`.
