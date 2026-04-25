# Halcyon-Lab Trading Readiness Audit — Implementation Plan (v3)

**Paired with:** `audit-spec.md`, `design-decisions.md`

**Schema:** `/arcis:code` Planner task_graph

**Executor:** `/arcis:code --plan docs/audits/2026-04-27-trading-readiness/plan.md`

---

## task_graph

```json
{
  "tasks": [
    {
      "id": "T1.01",
      "name": "Pre-#651 quarantine sweep on shadow_trades",
      "description": "Mark quarantined=1 on shadow_trades rows whose entry_timestamp is before commit #651 (cutoff: 2026-04-22T20:00:00-04:00 ET, reconfirm via `git log -1 --format=%aI <merge-commit-sha>` at task start; document in commit message). Run during Sat 06:00-08:00 ET maintenance window OR with exclusive write lock. Post-task: re-run identical SELECT predicate; assert zero new matches. In-flight rule: entry pre-cutoff + exit post-cutoff \u2192 quarantine. Backfill per memory pattern ('{}' not NULL, batch commits \u226550).",
      "files_in_scope": [
        "scripts/quarantine_pre_651.py (NEW)",
        "tests/scripts/test_quarantine_pre_651.py (NEW)"
      ],
      "files_read_only": [
        "src/schema/registry.py",
        "src/shadow_trading/ledger.py"
      ],
      "depends_on": [],
      "test_strategy": "(1) positive pre-cutoff \u2192 quarantined=1; (2) negative post-cutoff \u2192 0; (3) boundary at 2026-04-22T20:00:00-04:00 (pre, by spec); (4) in-flight entry-pre/exit-post \u2192 1; (5) idempotency. Plus integration: post-task SELECT returns zero.",
      "scope_fence": "Do NOT modify schema. Do NOT touch attribution_trades or walkforward_trades (T1.05). If lock unavailable AND maintenance window missed, ABORT.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T1.05",
      "name": "Extend quarantined column to attribution_trades + walkforward_trades",
      "description": "Add quarantined BOOLEAN NOT NULL DEFAULT 0 to attribution_trades (line ~1626) and walkforward_trades (line ~2178) via src/schema/registry.py. Propagate flag from shadow_trades by JOIN on trade_id. Migration backfills existing rows.",
      "files_in_scope": [
        "src/schema/registry.py",
        "scripts/quarantine_propagation_migration.py (NEW)",
        "tests/test_quarantined_propagation.py (NEW)"
      ],
      "files_read_only": [
        "src/shadow_trading/ledger.py",
        "scripts/quarantine_pre_651.py"
      ],
      "depends_on": [
        "T1.01"
      ],
      "test_strategy": "(1) attribution write reads quarantined; (2) walkforward write reads quarantined; (3) backfill preserves data; (4) read-side filter works.",
      "scope_fence": "Schema change ONLY in src/schema/registry.py. Do NOT add quarantined to other tables. Run `python -m src.main validate-schema --fix` after registry edit.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T1.03",
      "name": "Canonical Sharpe module + 12 call-site migration",
      "description": "Create src/analytics/canonical_sharpe.py (NEW; parent src/analytics/ exists with spy_benchmark.py sibling) exposing raw_sharpe, spy_relative_sharpe, rf_adjusted_excess_sharpe (all 252-scaled). Migrate F-2 sites: src/journal/stats.py:114-130 _trade_sharpe (PROD-FORMULA \u221an) \u2192 canonical; src/platform/metrics.py:32-48 compute_sharpe/compute_excess_sharpe \u2192 canonical (preserve API for walkforward downstream); src/api/cloud_routes/trades.py:58-69 _sharpe_with_se \u2192 keep wrapper, swap formula; src/evaluation/cto_report.py:239-246 inline \u221a150 \u2192 canonical; src/platform/rigor/cscv.py:37-45 _sharpe \u2192 RENAME to _sharpe_for_pbo (scale-invariant, keep math); src/evaluation/statistics.py:34-42 duplicate PSR \u2192 DELETE (canonical PSR at src/platform/rigor/dsr.py:50-64). KEEP: src/evaluation/statistics.py:18-23 sharpe_ratio (raw, gate_evaluator.py:58 correct); src/evaluation/model_monitor.py:61-66, 280-285 raw; src/scheduler/reports.py:837 raw. ESCALATE: src/evaluation/backtester.py:140-145 stride-5 sampler.",
      "files_in_scope": [
        "src/analytics/canonical_sharpe.py (NEW)",
        "tests/test_canonical_sharpe.py (NEW)",
        "src/journal/stats.py",
        "src/platform/metrics.py"
      ],
      "files_read_only": [
        "src/api/cloud_routes/trades.py",
        "src/evaluation/cto_report.py",
        "src/platform/rigor/cscv.py",
        "src/evaluation/statistics.py",
        "src/evaluation/gate_evaluator.py",
        "src/evaluation/model_monitor.py",
        "src/scheduler/reports.py",
        "src/evaluation/backtester.py",
        "src/notifications/telegram.py",
        "src/platform/rigor/walkforward.py",
        "src/platform/rigor/walkforward_runner.py",
        "src/platform/rigor/walkforward_metrics.py",
        "src/platform/rigor/dsr.py"
      ],
      "depends_on": [],
      "test_strategy": "Unit: 3 canonical functions vs hand-computed. Integration: each migrated site (stats._trade_sharpe, platform.metrics.compute_sharpe + compute_excess_sharpe) matches legacy on clean data; walkforward 252-scaling preserved. Boundary: zero-variance, single-trade, rf > mean. Renaming: import _sharpe_for_pbo succeeds; import _sharpe raises.",
      "scope_fence": "files_in_scope is 4. For OTHER read_only sites: if total touched files > 7, ESCALATE per Global Guardrail #8. Do NOT migrate src/risk/governor.py (no Sharpe references). Do NOT modify schema-stored Sharpe columns (forward-compat).",
      "estimated_complexity": "high"
    },
    {
      "id": "T1.04",
      "name": "Effective position-cap reconciliation (4 namespaces) + enabled-flag CI guardrail",
      "description": "PRIMARY (V3-2 restored intent): Add `effective_position_cap(config) -> int` at top of src/risk/governor.py. Returns min(...) of present caps from 4 namespaces: risk.max_open_positions (settings.local.yaml line 27-43), risk_governor.max_open_positions (line 142), live_trading.max_open_positions (line 154), bootcamp.max_positions (line 100). Modify RiskGovernor.__init__ (currently lines 385-404 reads only risk_governor.*) to call helper for max_open_positions. Modify src/shadow_trading/executor.py:_governor_cap (currently lines 104-113 reads only bootcamp/risk/shadow_trading) to call same helper. Log effective cap at startup. SIDE FEATURE (v2 retained): NEW tests/test_config_guardrails.py asserts no committed config/settings*.yaml has risk_governor.enabled: false.",
      "files_in_scope": [
        "src/risk/governor.py",
        "src/shadow_trading/executor.py",
        "tests/risk/test_cap_reconciliation.py (NEW)",
        "tests/test_config_guardrails.py (NEW)"
      ],
      "files_read_only": [
        "config/settings.local.yaml",
        "config/settings.example.yaml"
      ],
      "depends_on": [],
      "test_strategy": "Cap reconciliation: parametrize 16 combinations of presence/absence of 4 caps. Boundary: all 4 \u2192 min returned; only 1 \u2192 that value; none \u2192 fallback default 10 (matches existing). RiskGovernor.max_open_positions instance attr matches _governor_cap on identical config. Negative regression: synthetic divergent risk vs risk_governor caps returns min, not larger. Enabled-flag: glob settings*.yaml asserts not False; synthetic temp file with enabled: false detected (real configs not rejected).",
      "scope_fence": "Do NOT modify _count_live_open_positions or _enforce_position_cap body beyond cap source. Do NOT introduce new cap dimensions. The bootcamp early-return in executor.py:105 MUST be folded into min-rule (preferred) \u2014 document why in commit. If consumers OUTSIDE the 2 entry points need helper, ESCALATE.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T1.06",
      "name": "Bracket multiplier alignment with strategies.{name}.stop_atr_* config",
      "description": "Modify src/packets/template.py:154-186. Replace hardcoded stop_distance=2*atr (line 164) and target_prices=[price+1.5*atr, price+3.0*atr] (line 166) with config-driven values keyed off the existing `strategy` parameter (already passed in at line 158, 162). Read config.get('strategies', {}).get(strategy_name, {}).get('stop_atr_multiplier' OR 'stop_atr_multiple', 2.0). Pullback uses _multiplier (settings.local.yaml:210); MR uses _multiple (line 221). Accept both keys with priority _multiplier \u2192 _multiple \u2192 default 2.0. Map strategy aliases: pullback\u2192pullback; {mean_reversion, mr, meanreversion}\u2192mean_reversion. Confirm Alpaca submission carries resolved multiplier in stop_loss field via mocked submit_order.",
      "files_in_scope": [
        "src/packets/template.py",
        "src/services/scan_service.py",
        "src/services/mr_scan_service.py",
        "tests/test_bracket_config.py (NEW)"
      ],
      "files_read_only": [
        "config/settings.local.yaml",
        "config/settings.example.yaml",
        "src/shadow_trading/alpaca_adapter.py"
      ],
      "depends_on": [],
      "test_strategy": "Positive: strategy='mean_reversion' + config 2.5 \u2192 bracket stop_distance=2.5*ATR. Positive: strategy='pullback' + config 2.0 \u2192 2.0*ATR. Negative: missing config \u2192 default 2.0. Boundary: 0.0 flows through. End-to-end (DA-8): mock alpaca_adapter.submit_order, capture stop_loss arg, assert resolved_multiplier*test_atr. Race: config changed mid-run, subsequent order picks up new value.",
      "scope_fence": "Do NOT rename either config key (out of scope per \u00a711). Do NOT change defaults. Do NOT modify _resolve_strategy_brackets (line 162). Do NOT touch sizing logic (lines 154-159). If callers' strategy arg shape differs, ESCALATE.",
      "estimated_complexity": "low"
    },
    {
      "id": "T1.07",
      "name": "Startup Alpaca REST probe + go/no-go script + memo verification",
      "description": "Implement scripts/preflight_monday.py (NEW). Probes 5 Alpaca REST endpoints (account, positions, orders, clock, assets) via src/shadow_trading/alpaca_clients.py \u2014 timeout=5s each. Validates \u00a79 items 1-10 including memo content parsing and Signed-off-by trailer matching (verify arcis.yaml exists at task start; fallback config/settings.local.yaml; ESCALATE if neither). Writes audits/2026-04-27/preflight_transcript.txt with timestamps + per-item pass/fail + evidence. Non-zero exit on any GREEN-fail.",
      "files_in_scope": [
        "scripts/preflight_monday.py (NEW)",
        "tests/scripts/test_preflight_monday.py (NEW)"
      ],
      "files_read_only": [
        "src/shadow_trading/alpaca_clients.py",
        "src/shadow_trading/alpaca_adapter.py",
        "src/schema/registry.py",
        "audits/2026-04-27/stage1_baseline_memo.md"
      ],
      "depends_on": [
        "T1.01",
        "T1.05",
        "T1.03",
        "T1.04",
        "T1.06"
      ],
      "test_strategy": "Probe scenarios: fast-OK 200ms, slow-OK 4.5s, slow-fail 6s, hard-fail 500, intermittent 1-of-3-then-OK. Memo: positive/no-file/no-trailer/wrong-email. Mock all Alpaca per CLAUDE.md (no network in tests).",
      "scope_fence": "Do NOT modify src/shadow_trading/alpaca_clients.py. Do NOT submit orders during probe. Do NOT skip checklist items on early failure (transcript records all 10).",
      "estimated_complexity": "medium"
    },
    {
      "id": "T1.08",
      "name": "Fully-instrumented trade filter + statistical-power assessment",
      "description": "Implement src/analytics/instrumentation_filter.py (NEW; sibling of canonical_sharpe.py + spy_benchmark.py) exposing: (1) is_fully_instrumented(row: dict) -> bool — predicate; True iff pnl_pct, actual_entry_time, actual_exit_time, excess_return are all non-NULL and non-empty. (2) filter_fully_instrumented(rows) -> list[dict] — applies predicate, preserves order. (3) assess_statistical_power(n: int, target_sharpe: float = 0.0, alpha: float = 0.05) -> PowerAssessment — Bailey-LdP MinTRL-based; returns dataclass with (n, mintrl_required, status: 'powered' | 'underpowered' | 'marginal', message). T1.02's memo writer MUST surface: total in-window trades, quarantined excluded count, fully-instrumented N, MinTRL for target Sharpe=0, explicit verdict text. If N < MinTRL: memo MUST contain literal phrase 'Stage-1 sample is underpowered; reported Sharpe is not statistically reliable. Consider deferring promotion until N >= MinTRL.' Operator-requested 2026-04-25 amendment (v3.1).",
      "files_in_scope": [
        "src/analytics/instrumentation_filter.py (NEW)",
        "tests/analytics/test_instrumentation_filter.py (NEW)"
      ],
      "files_read_only": [
        "src/schema/registry.py",
        "src/journal/stats.py",
        "src/platform/rigor/dsr.py"
      ],
      "depends_on": [
        "T1.05"
      ],
      "test_strategy": "is_fully_instrumented: rows with all 4 required cols non-NULL pass; missing any col fails; empty-string treated as missing; None treated as missing. filter_fully_instrumented: mixed input returns only fully-instrumented, preserves input order. assess_statistical_power: known input pairs vs hand-computed Bailey-LdP MinTRL; boundary at exactly N==MinTRL (status='marginal'); N<MinTRL (status='underpowered'); N>=2*MinTRL (status='powered'). Integration: synthetic trade fixture with mixed instrumentation; filter+power chain produces expected verdict text.",
      "scope_fence": "Do NOT compute Sharpe in this module (canonical_sharpe.py owns that). Do NOT modify shadow_trades schema (T1.05 already extended). Do NOT modify T1.02's memo writer here — provide functions only; T1.02 imports. Do NOT add a power assessment for non-zero target_sharpe gating (out of scope; that's T2.04's promotion gate).",
      "estimated_complexity": "low"
    },
    {
      "id": "T1.02",
      "name": "Stage-1 honest baseline recompute + memo writer",
      "description": "Compute three Sharpe numbers (raw, SPY-relative, rf-adjusted canonical) over post-#651 quarantined-clean trade history. Use canonical_sharpe (T1.03). Politis-White block bootstrap inline (pending T2.02; flag dependency in memo) for 95% CIs. Emit audits/2026-04-27/stage1_baseline_memo.md (NEW) with \u00a79 item #9 mandatory contents. SPY-relative uses per-period SPY dividend yield (DA-9); if overflow, document constant haircut + window inline.",
      "files_in_scope": [
        "scripts/stage1_baseline_recompute.py (NEW)",
        "tests/scripts/test_stage1_baseline.py (NEW)",
        "audits/2026-04-27/stage1_baseline_memo.md (NEW)"
      ],
      "files_read_only": [
        "src/analytics/canonical_sharpe.py",
        "src/shadow_trading/ledger.py",
        "scripts/quarantine_pre_651.py",
        "src/analytics/spy_benchmark.py"
      ],
      "depends_on": [
        "T1.01",
        "T1.05",
        "T1.03",
        "T1.08"
      ],
      "test_strategy": "Memo writer produces all required sections including fully-instrumented N + MinTRL + power verdict (per T1.08). Integration: against fixture, Sharpe matches hand-computed. Dividend haircut: per-period vs flat 1.4% within 5-15 bps. Underpowered case: when N<MinTRL, memo contains the literal underpowered-warning phrase from T1.08.",
      "scope_fence": "Do NOT advance to Stage 2 methods. Do NOT auto-sign memo. Do NOT bypass canonical_sharpe.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.01",
      "name": "CPCV + anchored walk-forward harness",
      "description": "Implement src/methods/cpcv.py (NEW; src/methods/ directory NEW too \u2014 sibling to src/diagnostics/, src/evaluation/). CPCV per L\u00f3pez de Prado 2018 \u00a77.4. K=5 folds, embargo=10 sessions. Plus anchored walk-forward. Returns per-fold OOS rf-adjusted Sharpe via canonical_sharpe.",
      "files_in_scope": [
        "src/methods/__init__.py (NEW)",
        "src/methods/cpcv.py (NEW)",
        "tests/methods/test_cpcv.py (NEW)"
      ],
      "files_read_only": [
        "src/analytics/canonical_sharpe.py"
      ],
      "depends_on": [
        "T1.03"
      ],
      "test_strategy": "Synthetic edge \u2192 recovered. Null \u2192 mean \u2248 0. Embargo: no train-test overlap within 10 sessions.",
      "scope_fence": "Do NOT wire into promotion gate (T2.04).",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.02",
      "name": "Block bootstrap with Politis-White automatic block length",
      "description": "Implement src/methods/block_bootstrap.py (NEW). Stationary block bootstrap with Politis-White 1994 auto block-length. 10000 resamples default. Returns 95% CI of canonical rf-adjusted excess Sharpe.",
      "files_in_scope": [
        "src/methods/block_bootstrap.py (NEW)",
        "tests/methods/test_block_bootstrap.py (NEW)"
      ],
      "files_read_only": [
        "src/analytics/canonical_sharpe.py"
      ],
      "depends_on": [
        "T1.03"
      ],
      "test_strategy": "AR(1) synthetic: CI coverage \u2248 95%. Block length: white-noise \u2192 small; slow AR \u2192 larger.",
      "scope_fence": "Do NOT wire into promotion gate. Do NOT replace IID bootstrap callers.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.03",
      "name": "MC permutation test (label-shuffling under null)",
      "description": "Implement src/methods/mc_permutation.py (NEW). Trade-direction label shuffle under null. Returns empirical p-value.",
      "files_in_scope": [
        "src/methods/mc_permutation.py (NEW)",
        "tests/methods/test_mc_permutation.py (NEW)"
      ],
      "files_read_only": [
        "src/analytics/canonical_sharpe.py"
      ],
      "depends_on": [
        "T1.03"
      ],
      "test_strategy": "Edge \u2192 small p; null \u2192 uniform p. 1000 permutations default.",
      "scope_fence": "Do NOT extend to multi-strategy comparison (T2.05).",
      "estimated_complexity": "low"
    },
    {
      "id": "T2.04",
      "name": "Wire PSR/DSR/MinTRL + \u22654-of-5 promotion gate",
      "description": "Implement src/methods/psr.py (NEW) exposing psr/dsr/mintrl \u2014 may delegate to canonical PSR/DSR at src/platform/rigor/dsr.py:50-64, 67-109; MinTRL re-implemented or migrated from src/evaluation/statistics.py:45-54 (zero current consumers). Wire src/methods/promotion_gate.py (NEW) consuming T2.01..T2.05. Promotion = \u22654 of 5 at \u03b1=0.05 AND zero inverse hard-blocks. MinTRL diagnostic \u2014 N < MinTRL \u2192 defer.",
      "files_in_scope": [
        "src/methods/psr.py (NEW)",
        "src/methods/promotion_gate.py (NEW)",
        "tests/methods/test_psr.py (NEW)",
        "tests/methods/test_promotion_gate.py (NEW)"
      ],
      "files_read_only": [
        "src/methods/cpcv.py",
        "src/methods/block_bootstrap.py",
        "src/methods/mc_permutation.py",
        "src/methods/white_rc.py",
        "src/analytics/canonical_sharpe.py",
        "src/platform/rigor/dsr.py",
        "src/evaluation/statistics.py",
        "src/platform/promotion.py"
      ],
      "depends_on": [
        "T2.01",
        "T2.02",
        "T2.03",
        "T2.05"
      ],
      "test_strategy": "Boundary: 4-of-5 + 1 marginal-fail at p=0.051 \u2192 True. 3-of-5 \u2192 False. 5-of-5 + MC perm p=0.95 (inverse) \u2192 False. 5-of-5 + N < MinTRL \u2192 False (defer).",
      "scope_fence": "Do NOT bypass gate elsewhere. Do NOT alter pre-registered thresholds. Do NOT modify src/platform/promotion.py.",
      "estimated_complexity": "high"
    },
    {
      "id": "T2.05",
      "name": "White Reality Check (stationary bootstrap)",
      "description": "Implement src/methods/white_rc.py (NEW) per White 2000. Stationary bootstrap across competing strategies. Returns nominal-p.",
      "files_in_scope": [
        "src/methods/white_rc.py (NEW)",
        "tests/methods/test_white_rc.py (NEW)"
      ],
      "files_read_only": [
        "src/methods/block_bootstrap.py",
        "src/analytics/canonical_sharpe.py"
      ],
      "depends_on": [
        "T2.02"
      ],
      "test_strategy": "Multi-strat with dominant \u2192 small nominal-p. All-null \u2192 uniform. Tied Sharpes boundary.",
      "scope_fence": "Do NOT extend to SPA (Hansen 2005).",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.06",
      "name": "PBO writer (probability of backtest overfitting)",
      "description": "Implement src/methods/pbo.py (NEW) per Bailey-Borwein-L\u00f3pez de Prado-Zhu 2014. Emit numeric only.",
      "files_in_scope": [
        "src/methods/pbo.py (NEW)",
        "tests/methods/test_pbo.py (NEW)"
      ],
      "files_read_only": [
        "src/platform/rigor/cscv.py",
        "src/platform/rigor/walkforward_metrics.py"
      ],
      "depends_on": [],
      "test_strategy": "Synthetic noise \u2192 PBO \u2248 0.5; edge \u2192 PBO < 0.5.",
      "scope_fence": "Diagnostic only \u2014 do NOT wire as gate.",
      "estimated_complexity": "low"
    },
    {
      "id": "T2.07",
      "name": "Cost calibration from live fills",
      "description": "Extend src/platform/cost_calibration.py (existing, lines 37-95 contain calibrate_from_swing_history). Add live-fills source ingest path. Wire output to BacktestConfig consumer (currently unwired \u2014 Grep-confirm at task start).",
      "files_in_scope": [
        "src/platform/cost_calibration.py",
        "tests/test_cost_calibration_live.py (NEW)"
      ],
      "files_read_only": [
        "src/shadow_trading/ledger.py",
        "src/platform/rigor/walkforward_costs.py"
      ],
      "depends_on": [],
      "test_strategy": "Synthetic fills \u2192 recovered slippage. Boundary: 0 fills.",
      "scope_fence": "Do NOT touch backtester cost model directly (T2.08). Do NOT relocate file.",
      "estimated_complexity": "low"
    },
    {
      "id": "T2.08",
      "name": "Cost-grid sensitivity analysis",
      "description": "Implement src/methods/cost_sensitivity.py (NEW) running Stage-2 promotion gate over slippage_bps \u00d7 spread_bps grid. Reports gate-pass surface.",
      "files_in_scope": [
        "src/methods/cost_sensitivity.py (NEW)",
        "tests/methods/test_cost_sensitivity.py (NEW)"
      ],
      "files_read_only": [
        "src/methods/promotion_gate.py",
        "src/platform/cost_calibration.py"
      ],
      "depends_on": [
        "T2.04",
        "T2.07"
      ],
      "test_strategy": "Grid converges to known pass region under synthetic edge.",
      "scope_fence": "Do NOT auto-redeploy on grid output.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.09",
      "name": "PIT universe enforcement + per-period dividend-yield haircut",
      "description": "Wire src/platform/rigor/walkforward_universe.py (existing, PIT-correct at lines 92-125) into legacy backtester src/evaluation/backtester.py:45-46 (currently uses get_sp100_universe() from src/universe/sp100.py:31-136 \u2014 biased current S&P 100). Replace with PIT lookup keyed by as_of_date. Per-period SPY dividend yield via src/analytics/spy_benchmark.py (auto_adjust=True at lines 68-70 already handles dividend reinvestment \u2014 ensure no double-count).",
      "files_in_scope": [
        "src/evaluation/backtester.py",
        "tests/evaluation/test_backtester_pit.py (NEW)",
        "tests/test_dividend_yield_haircut.py (NEW)"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_universe.py",
        "src/universe/sp100.py",
        "src/analytics/spy_benchmark.py"
      ],
      "depends_on": [],
      "test_strategy": "Historical fixture: symbols added/removed on right dates. Per-period haircut matches SPY distribution; no double-count vs auto_adjust=True.",
      "scope_fence": "Do NOT use survivorship-biased universe. Do NOT remove get_sp100_universe() \u2014 verify via Grep; if zero callers, ESCALATE for separate cleanup.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.10",
      "name": "FRED ingestion + auto_adjust reconciliation (F-16 STALE caveat)",
      "description": "Per F-16 STALE: verify at task start whether auto_adjust=False flip still needed in src/data_ingestion/market_data.py:54, 68 \u2014 if not, scope shrinks. Implement src/data_ingestion/risk_free_rate.py (NEW) ingesting FRED 3-month T-bill series; cache via existing data_ingestion patterns.",
      "files_in_scope": [
        "src/data_ingestion/risk_free_rate.py (NEW)",
        "src/data_ingestion/market_data.py",
        "tests/data_ingestion/test_risk_free_rate.py (NEW)",
        "tests/data_ingestion/test_auto_adjust.py (NEW)"
      ],
      "files_read_only": [
        "src/analytics/spy_benchmark.py",
        "config/settings.local.yaml"
      ],
      "depends_on": [],
      "test_strategy": "FRED API mocked. auto_adjust flip preserves return invariants. Verify-then-skip if test #510 confirms current state OK.",
      "scope_fence": "Do NOT change yfinance pin. Do NOT touch src/analytics/spy_benchmark.py. Mock all FRED HTTP per CLAUDE.md.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.11",
      "name": "pandas_market_calendars NYSE",
      "description": "Replace ad-hoc holiday list at src/scheduler/holidays.py:14-25 (hardcoded 2026 set) with pandas_market_calendars.get_calendar('NYSE'). Preserve module-level export shape so downstream callers don't break.",
      "files_in_scope": [
        "src/scheduler/holidays.py",
        "tests/scheduler/test_holidays.py (NEW)"
      ],
      "files_read_only": [],
      "depends_on": [],
      "test_strategy": "Spot-check 5 known half-days + 3 holidays. Regression vs hardcoded 2026 set.",
      "scope_fence": "Do NOT add other exchanges. Do NOT relocate. Add pandas_market_calendars to requirements.txt if absent.",
      "estimated_complexity": "low"
    },
    {
      "id": "T2.12a",
      "name": "Capital allocator core (risk-parity)",
      "description": "Implement src/allocator/risk_parity_core.py (NEW; src/allocator/ NEW) \u2264 200 LOC. Per-symbol vol-targeting weights summing to 1, with floor/cap. Pure function.",
      "files_in_scope": [
        "src/allocator/__init__.py (NEW)",
        "src/allocator/risk_parity_core.py (NEW)",
        "tests/allocator/test_risk_parity_core.py (NEW)"
      ],
      "files_read_only": [],
      "depends_on": [],
      "test_strategy": "Hand-computed weights for 3-asset toy. Boundary: 1 asset, 100 assets, zero-vol asset.",
      "scope_fence": "Do NOT wire into live trading (T2.12b).",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.12b",
      "name": "Capital allocator wiring",
      "description": "Implement src/allocator/wiring.py (NEW) \u2264 200 LOC integrating T2.12a output with order sizing + governor approval. Order submission via src/shadow_trading/alpaca_adapter.py.",
      "files_in_scope": [
        "src/allocator/wiring.py (NEW)",
        "tests/allocator/test_wiring.py (NEW)"
      ],
      "files_read_only": [
        "src/allocator/risk_parity_core.py",
        "src/risk/governor.py",
        "src/shadow_trading/alpaca_adapter.py"
      ],
      "depends_on": [
        "T2.12a",
        "T1.04"
      ],
      "test_strategy": "End-to-end mocked: weights \u2192 sizes \u2192 governor approval \u2192 Alpaca order (mocked).",
      "scope_fence": "Do NOT submit real orders. Do NOT bypass governor.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.13",
      "name": "Delete 4 dead setup classifier classes",
      "description": "Per F-6c: src/features/setup_classifier.py 6-class taxonomy with 4 dead labels (breakout, momentum, range_bound, breakdown). Pre-removal Grep: confirm not consumed by _score_ticker (src/ranking/ranker.py:486-541) or engine.py:285. If consumer exists, ESCALATE. Delete dead class definitions; update remaining taxonomy.",
      "files_in_scope": [
        "src/features/setup_classifier.py",
        "tests/features/test_setup_classifier.py (NEW or extend)"
      ],
      "files_read_only": [
        "src/ranking/ranker.py",
        "src/features/engine.py"
      ],
      "depends_on": [
        "T1.03"
      ],
      "test_strategy": "Import scan: zero consumers of 4 dead labels. Negative: fixture emitting dead label \u2192 new code raises or maps. Live-label: surviving taxonomy still classifies original fixtures.",
      "scope_fence": "Do NOT touch live classes. Do NOT modify engine.py:285. If active consumer found, ESCALATE.",
      "estimated_complexity": "low"
    },
    {
      "id": "T2.14a",
      "name": "Pullback redesign \u2014 logistic features",
      "description": "Implement src/scoring/pullback_logistic/features.py (NEW; src/scoring/pullback_logistic/ NEW) \u2264 200 LOC. 5 features (returns_5d, vol_20d, rsi_14, drawdown_max_30d, volume_ratio_5d). Pure function returning DataFrame. Coexists with existing _score_ticker in src/ranking/ranker.py:486-541 (production path until T2.14c).",
      "files_in_scope": [
        "src/scoring/__init__.py (NEW)",
        "src/scoring/pullback_logistic/__init__.py (NEW)",
        "src/scoring/pullback_logistic/features.py (NEW)",
        "tests/scoring/pullback_logistic/test_features.py (NEW)"
      ],
      "files_read_only": [
        "src/features/indicators.py",
        "src/features/engine.py"
      ],
      "depends_on": [],
      "test_strategy": "Each feature vs hand-computed on fixture. Boundary: insufficient history \u2192 NaN.",
      "scope_fence": "Do NOT wire into model (T2.14b). Do NOT score signal (T2.14c). Do NOT modify _score_ticker.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.14b",
      "name": "Pullback redesign \u2014 logistic model",
      "description": "Implement src/scoring/pullback_logistic/model.py (NEW) \u2264 200 LOC. Logistic regression fit + persistence (sklearn). Trains on T2.14a features + labeled outcomes from shadow_trades historical exits.",
      "files_in_scope": [
        "src/scoring/pullback_logistic/model.py (NEW)",
        "tests/scoring/pullback_logistic/test_model.py (NEW)"
      ],
      "files_read_only": [
        "src/scoring/pullback_logistic/features.py",
        "src/shadow_trading/ledger.py"
      ],
      "depends_on": [
        "T2.14a"
      ],
      "test_strategy": "Synthetic separable \u2192 high AUC. Persistence round-trip preserves coefficients.",
      "scope_fence": "Do NOT introduce non-logistic models.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.14c",
      "name": "Pullback redesign \u2014 score adapter",
      "description": "Implement src/scoring/pullback_logistic/score.py (NEW) \u2264 200 LOC. Adapter producing pullback signal score (same numeric range as legacy _score_ticker) from features + model. Wired into src/ranking/ranker.py via new code path gated by config flag (default OFF). Migrates Sharpe accounting to canonical_sharpe.",
      "files_in_scope": [
        "src/scoring/pullback_logistic/score.py (NEW)",
        "src/ranking/ranker.py",
        "tests/scoring/pullback_logistic/test_score.py (NEW)"
      ],
      "files_read_only": [
        "src/scoring/pullback_logistic/features.py",
        "src/scoring/pullback_logistic/model.py",
        "src/analytics/canonical_sharpe.py"
      ],
      "depends_on": [
        "T2.14b",
        "T1.03"
      ],
      "test_strategy": "End-to-end: features \u2192 model \u2192 score on fixture. Flag OFF: ranker behavior identical pre-change. Flag ON: new path emits scores; numerical regression vs fixture-pinned values.",
      "scope_fence": "Do NOT replace _score_ticker \u2014 coexist. Do NOT change threshold check at ranker.py:611. Do NOT widen to other strategies.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.15",
      "name": "Lazy-prices spec shelving with revival ticket",
      "description": "Modify src/platform/specs/lazy_prices_v1.yaml (existing) \u2014 add status: shelved + revival_criteria block with re-activation thresholds. Pre-shelving Grep confirms no live consumer; if consumer exists, ESCALATE. (No Python directory src/strategies/lazy_prices/ \u2014 only the YAML.)",
      "files_in_scope": [
        "src/platform/specs/lazy_prices_v1.yaml",
        "tests/platform/specs/test_lazy_prices_shelved.py (NEW)"
      ],
      "files_read_only": [
        "src/platform/strategy_spec.py",
        "src/platform/_strategy_spec_ranking.py"
      ],
      "depends_on": [],
      "test_strategy": "Import scan: zero live consumers post-shelve. Loader test: spec parses with new fields.",
      "scope_fence": "Do NOT delete YAML \u2014 modify in place. Do NOT delete plugin module yet (T2.18).",
      "estimated_complexity": "low"
    },
    {
      "id": "T2.16a",
      "name": "Factor model alpha \u2014 core (Stage 3 only)",
      "description": "Implement src/methods/factor_alpha_core.py (NEW) \u2264 200 LOC. Fama-French 3+momentum regression returning alpha + t-stat. Pure function. Stage 3 only.",
      "files_in_scope": [
        "src/methods/factor_alpha_core.py (NEW)",
        "tests/methods/test_factor_alpha_core.py (NEW)"
      ],
      "files_read_only": [
        "src/data_ingestion/risk_free_rate.py"
      ],
      "depends_on": [
        "T2.10"
      ],
      "test_strategy": "Synthetic with injected alpha \u2192 recovered. Zero-alpha null boundary.",
      "scope_fence": "Stage 3 only \u2014 do NOT wire into Stage-2 promotion.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.16b",
      "name": "Factor model alpha \u2014 wiring",
      "description": "Implement src/methods/factor_alpha_wiring.py (NEW) \u2264 200 LOC. Integrates T2.16a with src/scheduler/reports.py via additive hook. Stage 3 attribution writer.",
      "files_in_scope": [
        "src/methods/factor_alpha_wiring.py (NEW)",
        "tests/methods/test_factor_alpha_wiring.py (NEW)"
      ],
      "files_read_only": [
        "src/methods/factor_alpha_core.py",
        "src/scheduler/reports.py"
      ],
      "depends_on": [
        "T2.16a"
      ],
      "test_strategy": "End-to-end: alpha computed \u2192 written to report. Insufficient-history boundary.",
      "scope_fence": "Stage 3 only. Do NOT modify src/scheduler/reports.py.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.17",
      "name": "Fix is_connected + fail-closed governor on 5 surfaces",
      "description": "5 fail-OPEN \u2192 fail-CLOSED: (1) is_connected post-handshake (in src/shadow_trading/alpaca_adapter.py or alpaca_clients.py \u2014 verify exact location), (2) get_account_equity, (3) get_position_value, (4) get_buying_power, (5) get_open_orders. Each raises GovernorInputMissingError (NEW exception) on missing input. src/risk/governor.py catches and halts. Negative test PER SURFACE.",
      "files_in_scope": [
        "src/risk/governor.py",
        "src/shadow_trading/alpaca_adapter.py",
        "tests/risk/test_fail_closed.py (NEW)",
        "tests/shadow_trading/test_alpaca_is_connected.py (NEW)"
      ],
      "files_read_only": [
        "src/shadow_trading/alpaca_clients.py"
      ],
      "depends_on": [
        "T1.04"
      ],
      "test_strategy": "Parametrize all 5 surfaces \u2014 each negative raises GovernorInputMissingError \u2192 halt. Positive: all 5 healthy \u2192 approve.",
      "scope_fence": "Do NOT add new governor inputs. If surface helper doesn't exist as separate function, document and ESCALATE. Do NOT touch T1.04 cap helper.",
      "estimated_complexity": "medium"
    },
    {
      "id": "T2.18",
      "name": "Remove plugin interface (-300 LOC)",
      "description": "Remove src/platform/strategy_plugin.py (lines 34-71) and src/platform/plugin_registry.py (lines 19-43). Pre-deletion Grep for `from src.platform.strategy_plugin`, `from src.platform.plugin_registry`, `@register_plugin` (zero in src/ at audit time \u2014 re-verify). If any production importer (including src/platform/strategy_spec.py YAML loader after T2.15), block. Clean up imports in src/platform/__init__.py.",
      "files_in_scope": [
        "src/platform/strategy_plugin.py",
        "src/platform/plugin_registry.py",
        "src/platform/__init__.py",
        "tests/platform/test_plugin_removal.py (NEW)"
      ],
      "files_read_only": [
        "src/platform/specs/lazy_prices_v1.yaml",
        "src/platform/strategy_spec.py"
      ],
      "depends_on": [
        "T2.15"
      ],
      "test_strategy": "Import scan: zero consumers. Negative: imports raise ImportError. Repo-wide grep returns only test files.",
      "scope_fence": "If non-test consumer found, ESCALATE \u2014 do NOT leave broken imports. Do NOT delete src/platform/specs/, strategy_spec.py, or unrelated platform modules.",
      "estimated_complexity": "low"
    },
    {
      "id": "T3.01",
      "name": "Devil's-advocate of Stage-1 baseline (docs only)",
      "description": "Write audits/2026-04-27/devils_advocate_stage1.md (NEW). Enumerate 5 ways baseline could be wrong (selection bias, look-ahead remnants, cost mismodel, regime shift, survivorship); for each, falsifying evidence.",
      "files_in_scope": [
        "audits/2026-04-27/devils_advocate_stage1.md (NEW)"
      ],
      "files_read_only": [
        "audits/2026-04-27/stage1_baseline_memo.md"
      ],
      "depends_on": [
        "T1.02"
      ],
      "test_strategy": "Manual review by operator.",
      "scope_fence": "Docs only \u2014 no code.",
      "estimated_complexity": "low"
    },
    {
      "id": "T3.02",
      "name": "Independent recompute via direct sqlite3",
      "description": "Implement scripts/independent_baseline_recompute.py (NEW) using direct sqlite3 (no src.shadow_trading or src.journal indirection). Compares to T1.02 memo; flags >5% divergence. Reads ARCIS_DB_PATH env var per CLAUDE.md (canonical C:/arcis/data/ai_research_desk.sqlite3). Read-only URI mode.",
      "files_in_scope": [
        "scripts/independent_baseline_recompute.py (NEW)",
        "tests/scripts/test_independent_recompute.py (NEW)"
      ],
      "files_read_only": [
        "audits/2026-04-27/stage1_baseline_memo.md"
      ],
      "depends_on": [
        "T1.02"
      ],
      "test_strategy": "Synthetic divergence >5% triggers flag. Match within 5% silent.",
      "scope_fence": "Do NOT use any src.shadow_trading or src.journal code. Do NOT write to DB (read-only URI).",
      "estimated_complexity": "medium"
    }
  ],
  "execution_order": [
    [
      "T1.01",
      "T1.04",
      "T1.06",
      "T2.06",
      "T2.10",
      "T2.13",
      "T2.15",
      "T2.11",
      "T2.07",
      "T2.09",
      "T2.12a",
      "T2.14a"
    ],
    [
      "T1.05",
      "T1.03",
      "T2.18"
    ],
    [
      "T1.07",
      "T1.08",
      "T1.02",
      "T2.01",
      "T2.02",
      "T2.03",
      "T2.17",
      "T2.14b",
      "T2.16a"
    ],
    [
      "T2.05",
      "T2.14c",
      "T2.16b",
      "T2.12b"
    ],
    [
      "T2.04"
    ],
    [
      "T2.08",
      "T3.01",
      "T3.02"
    ]
  ],
  "notes": "v3 path-verification rule: every path is Glob-verified or marked (NEW). v3 corrections vs v2: replaced fabricated src/strategies/{mr,pullback,breakout}/, src/risk_governor/, src/live_trading/, src/bootcamp/, src/metrics/, src/brokers/alpaca/, src/plugins/, src/_archived/ with verified-real src/risk/governor.py, src/shadow_trading/{executor,alpaca_adapter,alpaca_clients,ledger}.py, src/packets/template.py, src/services/{scan_service,mr_scan_service}.py, src/ranking/ranker.py, src/features/{mean_reversion,setup_classifier,engine}.py, src/journal/stats.py, src/notifications/telegram.py, src/api/cloud_routes/trades.py, src/evaluation/{cto_report,statistics,gate_evaluator,model_monitor,backtester}.py, src/platform/{metrics,strategy_plugin,plugin_registry,cost_calibration,promotion,strategy_spec}.py, src/platform/rigor/{cscv,dsr,walkforward,walkforward_runner,walkforward_metrics,walkforward_universe,walkforward_costs}.py, src/scheduler/{reports,holidays}.py, src/data_ingestion/market_data.py, src/analytics/spy_benchmark.py, src/universe/sp100.py, src/platform/specs/lazy_prices_v1.yaml. T1.04 reframed back to CAP-reconciliation primary task per V3-2 charge.\n\nTask ID-to-Ordinal table (ordinals comments only): 1=T1.01, 2=T1.05, 3=T1.03, 4=T1.04, 5=T1.06, 6=T1.07, 7=T1.02, 8=T2.01, 9=T2.02, 10=T2.03, 11=T2.04, 12=T2.05, 13=T2.06, 14=T2.07, 15=T2.08, 16=T2.09, 17=T2.10, 18=T2.11, 19=T2.12a, 20=T2.12b, 21=T2.13, 22=T2.14a, 23=T2.14b, 24=T2.14c, 25=T2.15, 26=T2.16a, 27=T2.16b, 28=T2.17, 29=T2.18, 30=T3.01, 31=T3.02. Total 31 tasks (preserved from v2).\n\nGlobal guardrails: (1) File LOC \u2264 400; functions \u2264 60. T2.14a/b/c, T2.12a/b, T2.16a/b each \u2264 200. (2) Schema authority src/schema/registry.py only; run validate-schema --fix per CLAUDE.md. (3) Test floor 2897 (CLAUDE.md); bump baseline if sweep grows. (4) Mock all external APIs (CLAUDE.md). (5) Never bypass governor. (6) Forward+backward compat. (7) v3 path discipline: every path Glob-verified OR (NEW); fabrications forbidden. (8) Scope-fence escalation: >2 files outside files_in_scope \u2192 escalate. (9) Monday-blocking tasks (T1.01, T1.03, T1.04, T1.06, T1.07, T2.04, T2.17) must include positive + negative + boundary + race/timeout tests. (10) audits/2026-04-27/ deliverables checked-in.\n\nCritical-path: Sat (Batch 1) \u2192 Sat-Sun (Batch 2) \u2192 Sun-Mon AM (T1.07, T1.02, T2.17) \u2192 operator memo sign-off \u2192 T1.07 final \u2192 live trading enabled. T2.04 promotion gate is Stage-2 prerequisite, NOT Monday-blocking."
}
```
