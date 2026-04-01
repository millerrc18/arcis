# Arcis Codebase Audit Report
**Date:** 2026-03-25
**Auditor:** Claude Code

## Summary
- Total files reviewed: 160 (135 Python + 25 frontend)
- Total lines reviewed: 22,398 (20,068 Python + 2,330 frontend)
- Issues found by previous audit: 11
- Issues fixed: 11
- New issues found by this audit: 7
- New issues fixed: 5
- Remaining items (deferred): 2

## Issues Fixed

### From Previous Audit

**Issue 1 — Default equity fallback ($5K) in governor.py (MEDIUM)**
The `get_portfolio_state()` function used `equity = 5000.0` as the default when Alpaca was unreachable. For a $100K account, this caused the risk governor to compute position sizes 20x too small. Fixed by reading `risk.starting_capital` from config (default 100000). The except-pass block was also upgraded to `logger.debug`.

**Issue 2 — LLM client ignores active model version (MEDIUM)**
`_get_llm_config()` in `src/llm/client.py` always returned the config YAML model (`qwen3:8b`), ignoring any fine-tuned model registered via the versioning system. Fixed by checking `get_active_model_name()` first — if a trained model is active and not "base", it overrides the config default. Also added a `logger.warning` in the watch loop startup when there's a mismatch between config model and active model.

**Issue 3 — Dual WebSocket connections (MEDIUM)**
`App.jsx` created one WebSocket for TanStack Query cache invalidation, and `useWebSocket.js` created a second for the ActivityFeed. Fixed by creating `frontend/src/contexts/WebSocketContext.jsx` that manages a single shared connection. `App.jsx` now uses a `CacheInvalidator` component that subscribes to the shared context, and `useWebSocket.js` is a thin wrapper around the context. Result: 1 connection instead of 2, same functionality. Also fixed a variable shadowing bug where `const type` was reassigned inside the `trade_closed` handler.

**Issue 4 — Hardcoded $100K in fund metrics (LOW)**
`_compute_fund_metrics()` in `src/evaluation/cto_report.py` used `total_pnl / 100000` for total return calculation. Fixed to read `risk.starting_capital` from config.

**Issue 5 — Duplicate `_slope_direction` function (LOW)**
Identical 12-line function existed in both `src/features/engine.py` and `src/features/regime.py`. Removed the copy in `regime.py` and added `from src.features.engine import _slope_direction`.

**Issue 6 — Duplicate `trigger_scan` route name (LOW)**
Both `src/api/routes/scan.py` and `src/api/routes/actions.py` had a function named `trigger_scan`. While they resolved to different URL paths (`/api/scan` vs `/api/actions/scan`), the name collision was confusing. Renamed the actions version to `action_trigger_scan`.

**Issue 7 — Silent except-pass blocks (LOW)**
Upgraded ~9 `except Exception: pass` blocks to `except Exception as e: logger.debug(...)` in:
- `src/risk/governor.py` (2 locations: Alpaca account, current price)
- `src/services/system_service.py` (3 locations: Alpaca, journal DB, training counts)
- `src/evaluation/cto_report.py` (3 locations: validation, leakage, quadrants)
- `src/training/ab_evaluation.py` (1 location: scoring)

Broadcast_sync wrappers and migration compatibility blocks were left intentionally silent per instructions.

**Issue 8 — Unused imports (LOW)**
Removed unused imports across 7 files:
- `src/main.py`: `update_shadow_trade`, `update_recommendation`, `get_active_model_version`, `get_model_history`
- `src/evaluation/cto_report.py`: `json`, `sqlite3`, `Counter`
- `src/features/engine.py`: `numpy as np`
- `src/training/ab_evaluation.py`: `json`
- `src/training/validation.py`: `json`
- `frontend/src/components/Layout.jsx`: `Activity` from lucide-react
- `frontend/src/pages/Dashboard.jsx`: `LineChart`, `Line` from recharts

**Issue 9 — print statements in library code (LOW)**
Replaced ~60 `print()` calls with `logger.info()` or `logger.warning()` across 13 library modules: `packet_writer.py`, `postmortem_writer.py`, `watchlist_writer.py`, `engine.py`, `earnings.py`, `market_data.py`, `notifier.py`, `executor.py`, `alpaca_adapter.py`, `backfill.py`, `bootstrap.py`, `data_collector.py`, `historical_data.py`. Removed `import sys` where it was only used for `sys.stderr` in print calls and added `import logging` + logger setup where missing.

**Issue 10 — Example config starting_capital (LOW)**
Changed `starting_capital: 1000` to `starting_capital: 100000` in `config/settings.example.yaml` with a comment explaining it should match the paper trading account.

**Issue 11 — Legacy TRAIN_SCRIPT (LOW)**
Added deprecation comments to the legacy `TRAIN_SCRIPT` variable in `src/training/trainer.py`, noting it uses the old Unsloth API and that `CURRICULUM_TRAIN_SCRIPT` is the primary training path using standard PEFT/TRL 0.24.

### New Issues Found and Fixed

**N1 — `get_metric_history` ignores `days` parameter (BUG)**
`src/training/versioning.py` line 186: The function accepted a `days` parameter but the SQL query had no WHERE clause, returning ALL snapshots regardless. Fixed by computing a cutoff date and adding `WHERE snapshot_date >= ?`.

**N2 — Resource leak in system_service.py (BUG)**
`src/services/system_service.py` line 69: `sqlite3.connect()` was used without a context manager. If either `SELECT` statement raised an exception, `conn.close()` would never be called. Fixed by using `with sqlite3.connect(...) as conn:`.

**N3 — Misleading `operating_margin` label (INCORRECT)**
`src/data_enrichment/fundamentals.py` line 211: The variable named `operating_margin` was computed as `net_income_ttm / revenue_ttm`, which is net margin, not operating margin. Renamed the local variable to `net_margin` and updated the formatter to display "Net Margin" instead of "Op Margin". The dict key was left as `operating_margin` to maintain API compatibility.

**N4 — `leakage_test_accuracy` key mismatch (BUG)**
`src/evaluation/cto_report.py` line 476: Referenced `leakage.get("test_accuracy")` but `check_outcome_leakage()` returns `balanced_accuracy`. Fixed to use the correct key.

**N5 — Unused `HISTORICAL_TRAINING_PROMPT` import (CLEANUP)**
`src/training/historical_scanner.py`: Imported but never referenced. Removed.

## Remaining Items (Deferred)

**D1 — Dashboard and Training inline toast state**
`Dashboard.jsx` (line 23) and `Training.jsx` (line 11) maintain their own inline toast state for action button feedback, despite the global `Toast` system in `App.jsx`. These work correctly but create a slight inconsistency. Deferred because fixing requires refactoring the action button feedback pattern and the current behavior is correct.

**D2 — `Roadmap.jsx` uses raw `fetch()` instead of `api` module**
`Roadmap.jsx` (line 368) calls `fetch('/api/cto-report?days=30')` directly instead of using the `api.getCtoReport()` function. Functions correctly but is inconsistent with the rest of the codebase. Deferred as low-priority cosmetic issue.

## Architecture Observations

**Strengths:**
- Clean separation of concerns: CLI (`main.py`) -> services -> business logic -> data layer
- The service layer pattern (`src/services/`) successfully decouples API routes from business logic
- Self-blinding training pipeline is architecturally sound — outcome data is genuinely segregated from analysis prompts
- Risk governor is well-designed with early-exit pattern and comprehensive checks
- Feature engine produces consistent, well-structured outputs
- The curriculum-based training pipeline (SFT -> DPO stages) is architecturally mature

**Weaknesses:**
- No authentication/authorization on any API endpoint. The `/api/config` PUT endpoint allows arbitrary config file modification without any access control.
- Hardcoded DB path `"ai_research_desk.sqlite3"` appears in ~15 locations. Should be centralized in config.
- The watch loop (`scheduler/watch.py` at 764 lines) is the largest single module and handles scheduling, pipeline orchestration, and overnight tasks. Consider splitting into separate scheduler and pipeline modules.
- `store.py` calls `initialize_database()` on nearly every read function, adding unnecessary overhead.
- `broadcast_sync` in `websocket.py` creates a new event loop with `asyncio.run()` which can fail in certain contexts. The 34+ except-pass blocks wrapping it mask these failures entirely.

**Scaling concerns:**
- SQLite will become a bottleneck with concurrent access from the watch loop, API server, and background tasks
- The single-threaded watch loop blocks on each task (no concurrent execution of independent overnight tasks)
- The backfill pipeline's O(n^2) deduplication check is capped at 200 examples, meaning it becomes unreliable for larger datasets

## Test Coverage Assessment

**Well-tested modules (good coverage):**
- Risk governor: All rejection paths, edge cases, kill switch
- Scorecard: Empty DB, populated DB, all section verification
- Shadow metrics: Empty, all-wins, all-losses, mixed, single trade
- Ranking: Determinism, sort order, candidate limits
- CTO report: Math, by-exit-reason, by-score-band, formatting
- Training versioning: Register, rollback, history ordering
- Quality filter/rubric: Scoring, classification tiers, edge cases

**Undertested modules (need tests):**
1. **Shadow executor** (`executor.py`, 413 lines): No unit tests for trade execution logic, bracket orders fallback path, or price monitoring. This is the most critical untested path.
2. **Watch loop** (`watch.py`, 764 lines): No tests for schedule logic, overnight pipeline, or error recovery. The 3-consecutive-error cooldown mechanism is untested.
3. **API routes** (`routes/*.py`): No integration tests for any endpoint. Response shapes are not validated.
4. **Data collection modules** (`data_collection/*.py`): No tests for CBOE, VIX, options, or macro collection pipelines.
5. **Alpaca adapter** (`alpaca_adapter.py`, 297 lines): Only bracket order tests exist. No tests for entry placement, exit placement, or account info retrieval.

**Pre-existing test failures (4):**
1. `test_leakage_detector.py::test_empty_database` — Key mismatch (`test_accuracy` vs `balanced_accuracy`)
2. `test_main_refactor.py::test_main_py_line_count` — Asserts `< 550 lines` but main.py is 620 lines
3. `test_self_blinding.py::test_stage1_receives_no_outcome` — Mock doesn't accept `purpose` kwarg
4. `test_self_blinding.py::test_stage2_receives_no_outcome` — Same mock issue

**Test quality concerns:**
- `test_ingestion.py` hits the network with no mocking (will fail in CI)
- `test_earnings.py` and `test_features.py` use `date.today()` (time-dependent)
- `test_trainer.py`, `test_training_data.py`, `test_versioning.py` use `_tmp_db()` that leaks temp files

## Database Schema Review

**15 tables identified:**
1. `recommendations` — Core trade recommendations. No obvious schema issues.
2. `shadow_trades` — Paper trade tracking. Links to recommendations via `recommendation_id`.
3. `training_examples` — Training data store. Has `quality_score_auto`, `source`, `difficulty_stage` columns.
4. `model_versions` — Model version registry. Tracks active/retired status.
5. `model_evaluations` — A/B evaluation results.
6. `audit_reports` — Daily audit reports with JSON assessment.
7. `metric_snapshots` — Historical KPI snapshots for trending.
8. `preference_pairs` — DPO training pairs.
9. `api_costs` — Claude API cost tracking.
10. `cboe_ratios` — CBOE put/call and skew data.
11. `options_chains` — Full options chain snapshots.
12. `options_metrics` — Computed options metrics (P/C ratio, IV, unusual volume).
13. `vix_term_structure` — VIX term structure data.
14. `macro_snapshots` — FRED macroeconomic data.
15. `google_trends` — Google Trends interest scores.

**Index assessment:**
- No explicit indexes beyond primary keys. The following queries would benefit from indexes:
  - `training_examples.source` (filtered frequently in quality analysis)
  - `shadow_trades.status` (filtered for open/closed queries)
  - `recommendations.created_at` (filtered by date range)
  - `metric_snapshots.snapshot_date` (sorted and filtered by date)
  - `options_chains.ticker, expiration_date` (queried per-ticker)

**Migration pattern:**
The codebase uses ALTER TABLE with try/except OperationalError for schema migrations. This is pragmatic for SQLite but doesn't track migration history. As the schema evolves, a proper migration system (e.g., Alembic) would prevent issues.

## Frontend Assessment

**Quality:** The React code is clean and well-structured. Components are appropriately sized and follow a consistent pattern (query data, handle loading/error, render).

**State management:** TanStack Query (react-query) handles all server state with polling intervals. No unnecessary client-side state management libraries. The new shared WebSocket context handles real-time updates cleanly.

**Potential issues:**
- Array index used as React key in `DataTable`, `ActivityFeed`, and `Packets`. Could cause rendering bugs if data reorders.
- `Docs.jsx` uses `dangerouslySetInnerHTML` for markdown rendering. Low risk since content comes from server-controlled files, but would be a vulnerability if doc content ever becomes user-supplied.
- No error boundaries at page level — only the top-level `ErrorBoundary` catches errors. A failing query in one page could crash the whole app.
- The recharts bundle contributes significantly to the 717KB JS bundle. Consider lazy-loading chart-heavy pages.

## Security Assessment

**No critical vulnerabilities found.**

**Observations:**
- All SQL queries use parameterized placeholders (`?`). No SQL injection vectors identified.
- No secrets in tracked files. API keys are loaded from `settings.local.yaml` (gitignored).
- `config/settings.example.yaml` uses obvious placeholder values.
- The `/api/config` PUT endpoint has no authentication — anyone with network access can modify the config file. This is acceptable for a local-only development tool but would need auth before any network exposure.
- `pickle.load()` is used for caching in `historical_data.py`, `fundamentals.py`, `insiders.py`, `macro.py`, and `news.py`. While the cache files are self-generated, pickle deserialization of tampered files could execute arbitrary code. Low risk in the current local-only context.
- SEC API requests include a hardcoded email address (`halcyonlabai@gmail.com`) as user agent.

## Recommendations for Next Sprint

1. **Add indexes to frequently queried columns** — `shadow_trades.status`, `training_examples.source`, `recommendations.created_at`, `metric_snapshots.snapshot_date`. Easy win for query performance.

2. **Fix pre-existing test failures** — 4 tests are broken. The `test_leakage_detector` key mismatch and `test_self_blinding` mock signature issues are straightforward fixes. The `test_main_py_line_count` assertion should either be removed or the threshold raised.

3. **Add tests for shadow executor** — The trade execution path (`executor.py`) is the most critical untested code. At minimum, test the price monitoring loop, bracket order fallback, and trade closing logic.

4. **Centralize DB path** — The hardcoded `"ai_research_desk.sqlite3"` appears in ~15 locations. Add a `get_db_path()` function to `config.py` that reads from config with a default.

5. **Split watch.py** — At 764 lines, this module handles too many concerns. Extract the overnight pipeline, scheduling logic, and individual task runners into separate modules.

6. **Add basic API authentication** — Even a simple API key check would prevent accidental config modifications from other processes on the same machine.

7. **Replace pickle caching with JSON** — The 5 enrichment modules use pickle for caching. JSON would be safer (no code execution risk) and more debuggable.

8. **Add network test markers** — `test_ingestion.py` hits the network without mocking. Add a `@pytest.mark.network` marker and skip by default in CI.

9. **Lazy-load heavy pages** — Use React.lazy() for `CTOReport`, `Roadmap`, and `Settings` pages to reduce initial bundle size from 717KB.

10. **Address `broadcast_sync` reliability** — The 34+ except-pass blocks wrapping `broadcast_sync` calls mask failures. Consider a more reliable WebSocket notification pattern or at minimum log failures.

## Codebase Statistics
- Python files: 135
- Python lines: 20,068
- Frontend files: 25
- Frontend lines: 2,330
- Test files: 35
- Test lines: 4,495
- Database tables: 15
- CLI commands: 43
- API endpoints: 45
- Research documents: 13
