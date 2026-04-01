# Sprint: Log Deep Audit + Fixes

> **Source:** `logs/arcis-audit-2026-04-01.log` — 6,882 lines, 37 hours of operation (March 30 19:17 → April 1 08:06 ET)
> **Scope:** Fix all errors, warnings, and anomalies found in production logs.
> **Priority:** These are PRODUCTION bugs affecting a live trading system.

**CRITICAL: Read the ENTIRE log file first. Run `python -m pytest tests/ -x -q` before AND after.**

---

## Task 1: Fix Double Logging (3,441 duplicate lines)

Every log message appears twice — once with module path prefix, once with `[INFO]`/`[ERROR]` prefix:
```
2026-03-30 19:17:27,674 [src.scheduler.watch] INFO: [WATCH] All SQLite tables verified/created
2026-03-30 19:17:27,674 [INFO] src.scheduler.watch: [WATCH] All SQLite tables verified/created
```

**Root cause:** Two handlers attached to the root logger OR a module-level + root-level handler conflict.

**Fix:** Audit `src/log_config.py` and all `logging.getLogger()` calls. Ensure exactly one handler per logger. Check for `propagate=True` on child loggers that also have their own handler.

**Test:** After fix, run watch loop for 1 min, verify each message appears exactly once.

---

## Task 2: Fix Render Postgres Missing Columns (76 errors)

### 2A: `shadow_trades.signal_price` does not exist (56 errors)
The `signal_price`, `fill_price`, `implementation_shortfall_bps`, and `strategy_type` columns are in `render_migrate.py` as ALTER TABLEs but they may not have run on Render yet. Verify these ALTER TABLEs are idempotent (IF NOT EXISTS equivalent for Postgres — use `DO $$ BEGIN ... EXCEPTION WHEN duplicate_column THEN NULL; END $$;`).

### 2B: `activity_log.level` does not exist (20 errors)
Same pattern — the `level` column ALTER TABLE exists but hasn't been applied. Make all ALTER TABLE migrations idempotent.

**Fix:** Wrap every ALTER TABLE ADD COLUMN in render_migrate.py with:
```sql
DO $$ BEGIN
  ALTER TABLE tablename ADD COLUMN colname TYPE;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
```

**Test:** Run `python scripts/render_migrate.py` — should succeed with zero errors even if columns already exist.

---

## Task 3: Fix `validate-system` Command (3 errors)

```
Command validate-system failed: _handle_validate_system() missing 1 required positional argument: 'config'
```

**Root cause:** The command executor calls `_handle_validate_system()` without passing the config dict.

**Fix:** Find the command handler in `src/commands/executor.py` and pass the config. Check other command handlers for similar missing arguments.

**Test:** Run validate-system via Telegram `/validate` or dashboard button — should complete without error.

---

## Task 4: Fix `research_papers.created_at` Missing Column (2 warnings)

```
[WATCH] notify_research_papers failed: no such column: created_at
```

**Root cause:** The notification query references `created_at` but the `research_papers` table uses `collected_at` as the timestamp column.

**Fix:** Update the query in the notification function to use `collected_at` instead of `created_at`.

**Test:** Trigger research paper notification — should succeed.

---

## Task 5: Fix LLM Timeouts (53 occurrences)

```
Read timed out. (read timeout=120)
```

53 timeouts out of ~350 LLM calls = ~15% failure rate.

**Investigate:**
1. Is the timeout configured correctly? Check `llm.timeout_seconds` in settings (should be 180 per Sprint 8 fix).
2. Are condensed-prompt retries working? Check if `_condensed_prompt_retry()` fires after first timeout.
3. Are there VRAM pressure issues causing slow inference? Check if timeouts cluster after VRAM handoff.
4. Log the actual inference duration on successful calls to establish baseline latency.

**Fix:** Ensure timeout matches config (180s). Add inference duration logging. If condensed retry isn't wired, wire it.

---

## Task 6: Fix DNS Resolution Failures (19 occurrences)

```
could not translate host name "dpg-..." to address: Name or service not known
Failed to resolve 'data.alpaca.markets'
```

**Root cause:** Intermittent DNS failures on Windows. 11 Render Postgres failures, 8 Alpaca failures.

**Fix:** 
1. Add retry with backoff on DNS resolution failures in render_sync.py connection logic
2. Add retry in alpaca_adapter.py price fetch
3. Consider caching DNS results (though this may be a Windows-level issue)

---

## Task 7: Fix SQLite `database is locked` Errors (8 occurrences)

```
Failed to update sync_state for options_metrics: database is locked
```

**Root cause:** Concurrent writes from sync thread + scan pipeline.

**Fix:** 
1. Verify all SQLite connections use `busy_timeout=5000` (Sprint 7 fix)
2. Increase busy_timeout to 10000ms in render_sync.py specifically (it can wait longer)
3. Add retry logic around sync_state updates

---

## Task 8: Audit Risk Governor Rejections

The logs show the risk governor is working correctly — rejecting trades for:
- Sector concentration (Health Care 55%, Utilities 4 positions, Consumer Staples 57%)
- Correlation limits (4 Industrials, 4 Utilities)

**No fix needed** — but document the rejection patterns. Are the thresholds too tight for bootcamp?

**Action:** Log a summary to `activity_log` at EOD with rejection counts by reason. Add to the EOD Telegram recap.

---

## Task 9: Architecture HTML Link in README

Add a link to the interactive architecture diagram in the README:
```markdown
See [Interactive Architecture (5W detail)](https://halcyonlab.app/architecture.html) for the full system diagram with expandable component details.
```

---

## Acceptance Criteria

- [ ] Each log message appears exactly once (no duplicates)
- [ ] `python scripts/render_migrate.py` succeeds with zero errors (idempotent ALTER TABLEs)
- [ ] `validate-system` command completes successfully
- [ ] Research paper notifications work (no `created_at` error)
- [ ] LLM timeout rate documented, condensed retry confirmed working
- [ ] DNS failures have retry logic
- [ ] SQLite locked errors have retry logic
- [ ] Risk rejection summary in EOD recap
- [ ] Architecture link in README
- [ ] All tests pass
- [ ] `npm run build` succeeds
