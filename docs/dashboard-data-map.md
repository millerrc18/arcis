# Dashboard Data Map

Complete data-flow mapping from database tables through API endpoints to
frontend calls for every page in the Halcyon Lab dashboard.

**Purpose:** When a KPI looks wrong, this document tells you exactly which
table, column, and endpoint to investigate.  When adding a new column or
renaming one, check here first so the frontend stays in sync.

**Architecture note:** The dashboard runs in two modes.  Local mode hits
`src/api/routes/` (raw SQLite).  Cloud mode hits `src/api/cloud_routes/`
(Render Postgres, synced from local).  Both expose the same URL paths
under `/api/...`; the tables and columns are identical.

---

## Dashboard (`/`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Paper Equity | `api.getAccount()` | `/api/shadow/account` | `shadow_trades` | `entry_price`, `planned_shares`, `pnl_dollars`, `status` |
| Open / Max | `api.getOpenTrades()` | `/api/shadow/open` | `shadow_trades`, `recommendations` | `status`, `recommendation_id` |
| Closed / 50 | `api.getClosedTrades()` | `/api/shadow/closed` | `shadow_trades`, `recommendations` | `status`, `actual_exit_time` |
| Win Rate | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `pnl_dollars`, `pnl_pct`, `actual_exit_time` |
| Profit Factor | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `pnl_dollars` |
| Max DD | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `pnl_dollars` (cumulative) |
| Activity Feed | `api.getActivityFeed()` | `/api/activity/feed` | `activity_log` | `event_type`, `detail`, `level`, `created_at` |
| Open Trades Table | `api.getOpenTrades()` | `/api/shadow/open` | `shadow_trades`, `recommendations` | `ticker`, `entry_price`, `pnl_dollars`, `pnl_pct`, `created_at` |

---

## Shadow Ledger (`/shadow`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Paper Equity | `api.getAccount()` | `/api/shadow/account` | `shadow_trades` | `entry_price`, `planned_shares`, `pnl_dollars`, `status` |
| Open / Max | `api.getOpenTrades()` | `/api/shadow/open` | `shadow_trades` | `status` |
| Closed / 50 | `api.getClosedTrades()` | `/api/shadow/closed` | `shadow_trades` | `status`, `actual_exit_time` |
| Win Rate | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `pnl_dollars`, `actual_exit_time` |
| Profit Factor | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `pnl_dollars` |
| Max DD | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `pnl_dollars` |
| Avg Slip (BPS) | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `signal_price`, `fill_price`, `implementation_shortfall_bps` |
| Avg R-Mult | `api.getMetrics()` | `/api/shadow/metrics` | `shadow_trades` | `pnl_dollars`, `stop_price`, `entry_price` |

---

## Live Ledger (`/live`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Live Equity | `api.getLiveSummary()` | `/api/live/summary` | `shadow_trades` | `source='live'`, `entry_price`, `pnl_dollars` |
| Live Trades | `api.getLiveTrades()` | `/api/live/trades` | `shadow_trades` | `source='live'`, `status`, `actual_exit_time` |

---

## CTO Report (`/cto-report`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Performance | `api.getCtoReport()` | `/api/cto-report` | `shadow_trades`, `recommendations` | `status`, `actual_exit_time`, `pnl_dollars`, `pnl_pct`, `market_regime` |
| Audit | `api.getCtoReport()` | `/api/cto-report` | `audit_reports` | `overall_assessment`, `summary` |
| Training | `api.getCtoReport()` | `/api/cto-report` | `training_examples`, `model_versions` | `COUNT(*)`, `version_name`, `status` |
| Scan metrics | `api.getCtoReport()` | `/api/cto-report` | `scan_metrics` | `llm_total`, `llm_success` |

The CTO report also joins `recommendations` to break down performance by
`setup_type`, `market_regime`, and `priority_score` bands.

---

## Training (`/training`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Example count | `api.getTrainingStatus()` | `/api/training/status` | `training_examples` | `COUNT(*)`, `source`, `outcome`, `quality_score_auto`, `curriculum_stage`, `ticker` |
| Model version | `api.getTrainingVersions()` | `/api/training/versions` | `model_versions` | `version_name`, `status`, `created_at` |
| Quality report | `api.getTrainingReport()` | `/api/training/report` | `training_examples` | `quality_score_auto`, `quality_score` |

---

## Health Score (`/health`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| HSHS score | `api.getHSHS()` | `/api/health/hshs` | computed | Geometric mean of 5 dimensions |
| Health detail | `api.getHealthScore()` | `/api/health/score` | `shadow_trades`, `training_examples`, `model_versions`, `scan_metrics`, `canary_evaluations` | `pnl_dollars`, `pnl_pct`, `source`, `regime_label`, `llm_success`, `llm_total`, `verdict` |
| Build Score | `api.getBuildScore()` | `/api/build-score` | `build_score_history` | `build_score`, `gate_velocity`, `system_health`, `data_asset_value`, `model_quality`, `research_velocity`, `reliability` |

---

## Council (`/council`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Latest session | `api.getCouncilLatest()` | `/api/council/latest` | `council_sessions` | `session_id`, `result_json`, `created_at` |
| Agent votes | `api.getCouncilSession(id)` | `/api/council/session/{id}` | `council_votes` | `session_id`, `agent_name`, `vote`, `reasoning`, `key_data_points`, `risk_flags` |
| History | `api.getCouncilHistory()` | `/api/council/history` | `council_sessions` | `created_at` |

---

## Settings (`/settings`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| API costs | `api.getCosts()` | `/api/costs` | `api_costs` | `model`, `purpose`, `input_tokens`, `output_tokens`, `cost_dollars`, `estimated_cost` |
| Config overrides | `api.getSettings()` | `/api/settings` | `config_overrides` | `setting_key`, `setting_value`, `updated_at` |

---

## DB Schema (`/schema`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Row counts | `api.getTableCounts()` | `/api/system/table-counts` | All whitelisted (49 tables) | `COUNT(*)` |

---

## Logs (`/logs`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Log entries | `api.getRecentLogs()` | `/api/logs/recent` | `log_entries` | `log_level`, `source`, `created_at` |

---

## Validation (`/validation`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| System checks | `api.getValidation()` | `/api/system/validation` | `validation_results` (cloud), computed (local) | `results_json`, `created_at` |

---

## Attribution (`/attribution`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Attribution stats | `api.getAttributionStats()` | `/api/attribution/stats` | `attribution_pairs` | `total_pairs`, `ranker_only`, `llm_portfolio`, `by_action`, `by_pair_type`, `statistical_power` |

---

## Stress Test (`/stress-test`)

| KPI | Frontend call | API endpoint | Tables | Key columns |
|-----|---------------|--------------|--------|-------------|
| Stress test results | `api.getStressTestResults()` | `/api/stress-test/results` | `stress_test_results` | `monthly_returns_json`, `regime_breakdown_json`, `equity_curve_json`, `created_at` |

---

## Pages with no direct DB dependency

| Page | Route | Data source | Table |
|------|-------|-------------|-------|
| Architecture | `/architecture` | Static JSX | none |
| Docs | `/docs` | `api.getDocsList()` / `api.getDoc(id)` | `research_docs` |
| Roadmap | `/roadmap` | Static JSX | none |
| Notes | `/notes` | `api.fetchNotes()` | `user_notes` |
| Packets | `/packets` | `api.getPackets()` | `recommendations` |

These pages read from the database but do not feed into the core trading
metrics pipeline, so they are lower risk during schema migrations.

---

## Critical tables

The following tables power the most dashboard surfaces and are highest risk
during schema changes:

| Table | Pages that depend on it |
|-------|------------------------|
| `shadow_trades` | Dashboard, Shadow Ledger, Live Ledger, CTO Report, Health Score, Build Score |
| `recommendations` | Dashboard, Shadow Ledger, CTO Report, Packets |
| `training_examples` | Training, CTO Report, Health Score |
| `model_versions` | Training, CTO Report, Health Score |
| `activity_log` | Dashboard (Activity Feed) |
| `build_score_history` | Health Score |
| `attribution_pairs` | Attribution |
| `stress_test_results` | Stress Test |

---

## Recent data-source changes (Sprint 1.A Wave 2+3)

The following changes affected tile data sources as of 2026-05-04. Check here before debugging stale or wrong KPI values.

### live_prices.sync_time_column now set (PR #918)

`live_prices` previously shipped with `sync_mode="latest_only"` but `sync_time_column=None`. This caused `RenderSyncThread` to build `MAX(None)` SQL → `sqlite3.OperationalError` on every sync cycle, so live price data never propagated to Postgres. Effect: `/api/shadow/open` returned `current_price_est=None`.

Fix: `sync_time_column="as_of"` (the existing alpaca timestamp column). After this fix, incremental sync works correctly and the Open Trades tile receives live prices from Render Postgres.

| Tile | Before #918 | After #918 |
|------|-------------|------------|
| Open Trades `current_price_est` | `None` (sync blocked) | Live Alpaca bid-ask midpoint via `live_prices.price` |
| `current_price_as_of` field | absent | Present (staleness detection available) |

### Win-rate / outcome aggregations now exclude reconciled_stale rows (PR #919 + #920)

New `EXCLUDED_FROM_OUTCOME_STATS = frozenset({'reconciled_stale'})` constant at `src/shadow_trading/exit_reason.py:62-64` is the canonical exclusion source.

New `outcome_stats_filter_sql()` helper at `src/shadow_trading/exit_reason.py:67-87` returns:
```
AND (exit_reason IS NULL OR exit_reason NOT IN ('reconciled_stale'))
```
(no leading space — callers prepend a space before appending to WHERE clauses)

Applied at 9 cloud route sites (#919 initial 4 sites + #920 5 additional) and 2 local route sites. The exit_reason histogram tile at `/api/cto-report` intentionally stays on unfiltered data (informational signal).

| Tile / endpoint | Filter applied |
|-----------------|----------------|
| Win rate (`/api/shadow/metrics`) | Yes — `outcome_stats_filter_sql()` appended |
| Profit factor (`/api/shadow/metrics`) | Yes |
| CTO Report headline KPIs | Yes |
| CTO Report by-score/sector/regime breakdowns | Yes |
| Strategy detail aggregations | Yes |
| Live summary | Yes |
| Account-level desk-filtered metrics | Yes |
| Projections win_rate / sharpe / drawdown | Yes |
| Training status per-model metrics | Yes |
| Exit reason histogram | No (intentional — surfaces reconciled_stale as signal) |

**Note:** 21+ additional sibling sites identified as needing the same filter are planned for Wave 4 H5. Until H5 merges, some secondary aggregations outside the above list may still include reconciled_stale rows.

---

## Column name gotchas

These column names have caused bugs or confusion in the past.  Check
carefully before writing queries.

| Column to use | Wrong guess | Why |
|---------------|-------------|-----|
| `market_regime` | `regime_label` | `recommendations` uses `market_regime`; `training_examples` uses `regime_label` for curriculum tagging -- they are different concepts |
| `cost_dollars` | `estimated_cost` | `api_costs` has both columns; the costs endpoint reads `COALESCE(cost_dollars, estimated_cost, 0)` so either can be NULL |
| `setting_key` / `setting_value` | `key` / `value` | The `config_overrides` table uses `setting_key` and `setting_value`, not bare `key`/`value` |
| `log_level` | `level` | `log_entries` uses `log_level`, not `level` |
| `actual_exit_time` | `exit_time` | `shadow_trades` stores the real exit timestamp in `actual_exit_time`; `exit_time` is not a column |
| `quality_score_auto` | `quality_score` | `training_examples` has both; the API uses `COALESCE(quality_score_auto, quality_score)` to prefer the auto-computed score |
| `pnl_dollars` / `pnl_pct` | `pnl` / `profit` | Always two separate columns, never a single `pnl` column |
| `source` (shadow_trades) | `trade_type` | Live trades are filtered by `source = 'live'`, not a separate `live_trades` table query in cloud mode |
| `curriculum_stage` | `regime_label` | `training_examples` uses `curriculum_stage` for grouping by training phase; `regime_label` is the market regime tag |
