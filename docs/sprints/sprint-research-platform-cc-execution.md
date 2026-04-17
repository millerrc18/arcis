# CC Execution Prompts — Strategy Research Platform (v0.24.0)

**Primary spec:** `docs/sprints/sprint-research-platform.md` (2,200+ lines)
**Deep research authority:**
- `docs/research/deep-research/backtest-rigor-retrofit-plan.pdf`
- `docs/research/deep-research/correlation-risk-monitoring-blueprint.pdf`
- `docs/research/deep-research/research-desk-design-report.md`

**Strategy:** 4 sequential sprints on 4 separate branches. CC's sprint-discipline rule ("never combine sprints into a mega-sprint") is respected. Each sprint is independently mergeable. Later sprints depend on earlier sprints landing first.

**Effort budget:** 50-72h across the 4 sprints. Sprint 1 is mandatory; Sprints 2-4 are all conditionally shippable based on time.

**Hard sequencing gates (non-negotiable):**
1. Sprint 1's DSR paper-example test must pass before any backtest result is trusted.
2. Sprint 3's hard exposure limits must land before Sprint 4's shadow harness activates any second strategy.
3. Sprint 3's defensive dashboard desk filtering must land before `desks.research.enabled: true` on any strategy.

---

# Sprint 1 of 4 — Platform Foundation + DSR Gate (feat/platform-foundation, ~14h)

**Copy everything below into CC:**

```
First, check out a new feature branch:

git checkout main
git pull origin main
git checkout -b feat/platform-foundation

You are now on branch feat/platform-foundation. Read docs/sprints/sprint-research-platform.md in full before starting. Your scope for THIS sprint is Tier 1 + Tier 2 only (see section "Honest Task Priority" in that spec). That means:

Tier 1 tasks (all mandatory, ~10h):
- Task 1: Strategy spec schema (1.5h) — includes the load_spec(strategy_id) helper (Pass-2-verified — prior spec had Task 9 calling an undefined function)
- Task 3: OHLCV data loader (1.5h) — thin adapter over src/simulation/cache.py:fetch_cached_ohlcv; do NOT reimplement parquet caching
- Task 4: Backtest engine core (4h, HIGH RISK) — reuses src/attribution/logger.py:simulate_mechanical_outcome directly; do NOT reimplement bracket logic
- Task 5a: Basic metrics (1h) — includes survivorship_haircut_bps parameter (-75/-200/-100 per strategy type per deep research)
- Task 5b: Deflated Sharpe Ratio (1h) — the 60 lines of verified Python code in the spec REPRODUCE THE PAPER'S WORKED EXAMPLE TO 4 DECIMALS. The unit test test_dsr_paper_example_reproduction is non-negotiable — if it fails, STOP and debug before continuing.
- Task 6: CLI + result persistence (1.5h) — 2 new tables: backtest_results + backtest_trades

Tier 2 tasks (~3-6h, concurrent with Tier 1 where possible):
- Task 0: EDGAR fetch pipeline repair (3-6h) — diagnostic first, then backfill at SEC rate limits. If it fails, platform still ships; Lazy Prices just returns candidates=0 with low_filing_data_coverage warning. Upstream blocker BUT non-blocking to this sprint's deliverables.
- Task 11: Lazy Prices YAML spec (3h) — written as data, not code. No backtest execution required in this sprint — just spec + feature provider functions.

Rules:
- Do NOT merge to main. Push to the feature branch only. Create a PR when done.
- Close GitHub issues on PR merge: none yet (Task 0 may close an issue if one was filed for EDGAR data)
- Follow the 3× Ralph Loop protocol for each task:
  Pass 1: Implement the feature/fix
  Pass 2: Review for gaps — check for stubs, TODOs, placeholder data, missing error handling, untested paths, data connections using mock instead of real data. Use repo grep (not memory) to verify every function/module reference. Every file path you write in code must exist or be something you're creating.
  Pass 3: Fix everything from Pass 2, polish, verify tests pass, verify build succeeds.

Non-negotiable quality gates (any one failing = Tier 1 not shipped):
1. test_dsr_paper_example_reproduction passes (DSR=0.9004, SR*_0_ann=0.5429 to 4 decimals). This single test IS the proof that the DSR implementation is correct. If it fails, the promotion gate is untrustworthy and nothing downstream is salvageable.
2. test_backtest_matches_hand_computed_example_scheduled passes (trivial "buy every Monday" strategy with hand-computed expected PnL).
3. test_backtest_matches_hand_computed_example_event_driven passes (seeded 3-filing scenario where only 1 should trigger entry based on cosine similarity threshold).
4. scripts/run_backtest.py --strategy lazy_prices_v1 --start 2020-01-01 --end 2024-12-31 produces EITHER a result with trades OR returns candidates=0 with a low_filing_data_coverage warning — but does NOT crash.

Codebase discipline (MUST follow — this is standard Arcis sprint discipline):
- No src/ file over 400 lines
- No function over 60 lines
- Refactor by extraction, not rewrite
- Never refactor AND add features in the same commit
- Every commit atomic (one logical change)

Before starting, run:
- pytest tests/ -q (baseline count)
- cd frontend && npm run build (baseline passing)
- python scripts/verify_docs.py (if present) to check doc state

After each major task, run:
- pytest tests/platform/ -v (the new tests you've added)
- pytest tests/ -x -q --timeout=60 (full suite; pass count must not decrease)

Specific Pass-2 verification points (these were caught in prior Ralph loops — DO NOT reintroduce):
- reconcile.py is ACTIVELY called from 4 places (src/scheduler/overnight.py:27, src/scheduler/position_monitor.py:69, src/scheduler/watch.py:685, src/cli/commands.py:405). This sprint does NOT touch reconcile — that's Sprint 4's work. But be aware it's live.
- /api/shadow/* endpoints live in src/api/cloud_routes/trades.py, NOT in a file called shadow.py (that file does not exist).
- There is no EquityCurveChart.jsx — if Task 12 charts show up later, they'll use Recharts directly (same pattern as Attribution.jsx, Council.jsx, Dashboard.jsx).
- There is no /api/shadow/status endpoint — actual endpoints are /api/shadow/open, /closed, /metrics, /account, /sharpe-attribution.
- Universe module is src/universe/sp100.py:get_sp100_universe — there is no sp500 module.
- trials_registry global N_eff counter counts EVERY backtest ever run including parameter sweeps — if you run 30 strategies × 10 param grid points, N_eff = 300 not 30 (per deep research, Bailey-López de Prado False Strategy theorem).

Update the following when done:
- MASTER.md Section 2 (volatile counts: new tests added, new files)
- CHANGELOG.md under [Unreleased] → add v0.24.0-alpha1 block
- RELEASES.md — new v0.24.0-alpha1 entry noting Tier 1+2 landed

Push to feature branch when complete:
  git push origin feat/platform-foundation

Then open a PR titled "v0.24.0-alpha1: Platform foundation + DSR gate" with a PR description that includes:
- Tests added: [count]
- Paper-example reproduction: [PASS/FAIL]
- Hand-computed validation: [PASS/FAIL]
- Lazy Prices dry-run behavior: [produced trades / candidates=0 / crashed]

Do NOT proceed to Sprint 2 scope. When PR merges, Sprint 2 starts on a fresh branch.

### Iteration 1 gaps found and fixed (Ralph-looped in spec, not re-loop here):
- All 29 Pass 1 findings fixed in commit 1b8b4d6 before this prompt was written
- All 4 Pass 2 repo-grep hallucinations fixed (EquityCurveChart.jsx, shadow.py, /api/shadow/status, missing load_spec helper)
- Full rigor retrofit applied in commit c3449ff (DSR + CSCV + walk-forward + hard exposure limits)
```

---

# Sprint 2 of 4 — Rigor Completion + Promotion Pipeline (feat/platform-rigor, ~8h)

**Precondition:** Sprint 1 PR merged to main. Main CI is green.

**Copy everything below into CC:**

```
First, confirm Sprint 1 has merged:

git checkout main
git pull origin main
git log --oneline -5 | grep -i "v0.24.0-alpha1\|platform foundation"

If you do not see the Sprint 1 merge, STOP — this sprint depends on it.

Then create a new feature branch:

git checkout -b feat/platform-rigor

You are now on branch feat/platform-rigor. Your scope for THIS sprint is Tier 3 only from docs/sprints/sprint-research-platform.md (see section "Honest Task Priority"). That means:

- Task 5c: CSCV / PBO (1h) — Combinatorially Symmetric Cross-Validation at S=16 partitions. Inputs: T×N PnL matrix from Task 4. Output: PBO scalar per selection campaign. Known failures documented in deep research (blind to look-ahead bugs, regime shifts, homogeneous-strategy degeneracy). Reject strategies with PBO > 0.5.
- Task 5d: Rolling walk-forward (1h) — Pardo 2008 annual train/test slide. Default 3y train / 1y test. Output: concatenated OOS equity curve, OOS efficiency (OOS_SR / IS_SR). Flag strategies with OOS efficiency < 0.3 as overfit.
- Task 8: Schema: add desk tag to shadow_trades (1h) — 3 new columns (desk, research_thesis, strategy_spec_hash) + index. Migration: ensure_columns on watch loop startup backfills all 85 existing rows to desk='swing' via DEFAULT clause.
- Task 10: Strategy registry + promotion states + trials_registry (3h) — 3 new tables. Gates REPLACE the 0.5 excess_sharpe gate with DSR ≥ 0.95 + PBO ≤ 0.50 + OOS efficiency ≥ 0.30. Manual promotions require justification_note ≥40 characters. expected_factor_profile_json and survivorship_haircut_bps columns added to strategy_registry.
- Task 5 bonus: survivorship haircut plumbing (~1h) — wire survivorship_haircut_bps from strategy_registry through compute_all_metrics into backtest_results.

Rules:
- Do NOT merge to main. Push to the feature branch only.
- Follow the 3× Ralph Loop protocol.
- Run the full test suite before and after. Pass count must not decrease.
- Frontend must build: cd frontend && npm run build
- Update MASTER.md Section 2 and CHANGELOG.md/RELEASES.md with v0.24.0-alpha2.
- Every commit atomic.
- Push to feature branch when complete:
  git push origin feat/platform-rigor

Non-negotiable quality gates:
1. test_pbo_rejects_overfit_strategy passes (seeded PnL matrix with known IS/OOS divergence returns PBO > 0.8)
2. test_pbo_accepts_stable_strategy passes (seeded stable performer returns PBO < 0.2)
3. test_walkforward_oos_efficiency_computed passes with known values
4. Migration on shadow_trades verified: all 85 existing rows have desk='swing' after ensure_columns runs
5. test_promote_shadow_trading_requires_justification_note passes (raises ValueError on <40 char note)
6. trials_registry N_eff counter increments correctly across backtests + sweeps

Codebase discipline (same as Sprint 1):
- No src/ file over 400 lines
- No function over 60 lines
- Refactor by extraction, not rewrite
- Every commit atomic

Specific implementation notes:
- src/platform/rigor/cscv.py is a new module. Keep it under 400 lines. The core logic is ~100 LOC per the deep research; remainder is tests.
- src/platform/rigor/walkforward.py is a new module. Keep the fold iteration loop in a helper so the main function stays under 60 lines.
- src/platform/promotion.py gets new logic; the file already exists from Sprint 1 as a stub if time allowed, or is being created fresh. Either way it stays under 400 lines.
- trials_registry counting logic lives in src/platform/rigor/dsr.py (a helper get_current_n_eff(db_path) that queries trials_registry) — DSR reads N_eff from there rather than accepting it as a parameter.

Before starting, repo-grep-verify (don't trust memory):
- grep -rn "simulate_mechanical_outcome" src/ — confirm it's still the signature we documented in Sprint 1's spec
- grep -rn "TABLE_DEFS\|_register\b" src/schema/ — confirm the TableDef/ColumnDef/IndexDef imports are correct for the 3 new tables
- grep -rn "ensure_columns" src/schema/ — confirm migration runs on watch loop startup

After each task, run:
- pytest tests/platform/rigor/ -v
- pytest tests/ -x -q --timeout=60

Push when complete. Open PR titled "v0.24.0-alpha2: CSCV + walk-forward + promotion pipeline + trials_registry" with test count delta and gate validation results.

Do NOT proceed to Sprint 3 scope.
```

---

# Sprint 3 of 4 — Defensive Dashboard + Hard Exposure Limits (feat/platform-safety, ~4h)

**Precondition:** Sprints 1 and 2 merged to main. Main CI green.

**Copy everything below into CC:**

```
Confirm Sprints 1 and 2 have merged:

git checkout main
git pull origin main
git log --oneline -10 | grep -E "v0.24.0-alpha1|v0.24.0-alpha2|platform foundation|platform rigor"

If either is missing, STOP.

Create a new feature branch:

git checkout -b feat/platform-safety

You are now on branch feat/platform-safety. Your scope for THIS sprint is Tier 4 only from docs/sprints/sprint-research-platform.md. That means:

- Task 12c: Defensive desk filtering (1h) — Dashboard.jsx gets a deskFilter dropdown (default 'swing' only). All shadow_trades-reading endpoints in src/api/cloud_routes/trades.py accept ?desk= query param with wildcard support (research_* matches all research strategies). Default-when-absent is swing-only, for backward compat.
- Task 11b.1: Correlation schema (0.5h) — 2 new tables: correlation_matrices + factor_loadings. Wire sync_to_postgres incremental.
- Task 11b.4: Hard exposure limits (2.5h) — src/platform/risk/exposure_limits.py with check_pre_trade_limits() enforced in code. HARD_LIMITS: 6% single-name, 25% sector, 1.5x gross leverage, 8% book drawdown circuit breaker. Never overridden during drawdown.

This sprint is called "platform-safety" because it's the minimum guard-rail set that must exist BEFORE Sprint 4's shadow harness can safely activate. Without Task 12c, main dashboard numbers silently lie when research strategies run. Without Task 11b.4, aggregate exposure across strategies is unconstrained.

Rules:
- Do NOT merge to main. Push to the feature branch only.
- Follow the 3× Ralph Loop protocol.
- Run the full test suite before and after. Pass count must not decrease.
- Frontend must build: cd frontend && npm run build
- Update MASTER.md and CHANGELOG.md/RELEASES.md with v0.24.0-alpha3.
- Push to feature branch when complete:
  git push origin feat/platform-safety

Non-negotiable quality gates:
1. Dashboard.jsx renders correctly with deskFilter=swing (existing 85 trades visible) AND deskFilter=all (same 85 trades since no research trades exist yet) — no JS errors in console.
2. GET /api/shadow/sharpe-attribution with no ?desk= param returns swing-only (backward compat preserved).
3. GET /api/shadow/sharpe-attribution?desk=all sums across desks (returns same data since no research desk trades exist yet).
4. GET /api/shadow/sharpe-attribution?desk=research_* wildcard matches all research strategies.
5. test_hard_limit_blocks_single_name_over_6pct passes (attempt 7% position → rejected).
6. test_hard_limit_blocks_sector_over_25pct passes.
7. test_drawdown_circuit_breaker_blocks_all_entries passes.
8. New tables correlation_matrices + factor_loadings declared with sync_to_postgres=True.

Specific implementation notes:
- Dashboard.jsx dropdown must populate 'swing' + any distinct desk values currently in shadow_trades (query at render, don't hardcode). Since only 'swing' exists today, dropdown shows [swing, all] only until research strategies run. Don't hardcode the list.
- src/api/cloud_routes/trades.py already has the shadow endpoints. Modify each to accept optional ?desk= query param. Use SQL LIKE when wildcard present, = otherwise.
- src/platform/risk/exposure_limits.py is new. Keep under 400 lines. check_pre_trade_limits should be pure (no DB writes) returning (allowed: bool, reason: str | None).
- The check_pre_trade_limits function is NOT yet wired into executor.py — that's Sprint 4's work. This sprint just creates the function + its tests.

Repo-grep-verify before starting:
- grep -rn "sharpe-attribution\|shadow/open\|shadow/closed" src/api/cloud_routes/trades.py — confirm endpoint locations haven't drifted
- grep -rn "deskFilter\|?desk=" frontend/src/ — should return 0 matches (this sprint introduces the pattern)

After each task, run:
- pytest tests/platform/risk/ -v
- pytest tests/test_cloud_app.py -v (confirm you didn't break shadow endpoints)
- cd frontend && npm run build

Push when complete. Open PR titled "v0.24.0-alpha3: defensive desk filtering + hard exposure limits".

Do NOT proceed to Sprint 4 scope.
```

---

# Sprint 4 of 4 — Shadow Harness + Dashboard Surfaces (feat/platform-shadow, ~17h)

**Precondition:** Sprints 1, 2, 3 merged to main. Main CI green. This is the big sprint — combine Tiers 5 + 6 because they're all the "deploy + visualize" layer.

**Copy everything below into CC:**

```
Confirm Sprints 1-3 have all merged:

git checkout main
git pull origin main
git log --oneline -15 | grep -E "v0.24.0-alpha[123]"

If any are missing, STOP.

Create a new feature branch:

git checkout -b feat/platform-shadow

You are now on branch feat/platform-shadow. Your scope for THIS sprint is Tier 5 + Tier 6 + select Tier 7/8 items from docs/sprints/sprint-research-platform.md:

Tier 5 (~8h):
- Task 7: Shadow harness (5h) — src/platform/shadow_harness.py. Writes to shadow_trades with desk='research_<strategy_id>'. PATCH strategy: modify src/shadow_trading/alpaca_adapter.py's _get_trading_client and _get_data_client helpers to accept optional desk kwarg. Thread desk through the 4 external call sites: executor.py:697, reconcile.py (all call paths — this is ACTIVELY called from overnight.py:27, position_monitor.py:69, watch.py:685), bracket_monitor.py, services/shadow_service.py. One helper change covers 12 internal alpaca_adapter call sites.
  - Inline per-desk client factory: src/shadow_trading/alpaca_clients.py with get_client(desk) + verify_accounts_distinct() assertion (prevents both desks pointing at same paper account — CRITICAL).
  - Wire check_pre_trade_limits (from Sprint 3) into ShadowHarness.run_one_tick before bracket order placement.
- Task 9: Watch loop platform integration (2h) — src/scheduler/watch.py gets _run_platform_shadow_tick using interval-gating pattern (NOT inline like _run_mr_scan per the explicit callout in the spec). self._last_platform_tick dict initialized in __init__, cleared in _reset_daily_state.
- Cost calibration from 85 swing trades (~1h) — src/platform/cost_calibration.py reads entry_slippage_bps + exit_slippage_bps from the 85 closed swing trades and computes calibrated defaults for BacktestConfig. Replaces the hardcoded 3/1.5 bps assumption.

Tier 6 (~6h):
- Task 12a: /research-platform page (3h) — frontend/src/pages/StrategyResearch.jsx with 4 sections: strategy registry table, strategy detail (expandable row with YAML), backtest results grid, promotion events log. New chart component BacktestEquityChart.jsx (uses Recharts directly, same pattern as Attribution.jsx).
- Task 12b: Action buttons (1.5h) — 3 POST endpoints: /api/platform/backtests, /api/platform/promotions, /api/platform/demotions. Promotions require confirmation_token + justification_note. Production promotion additionally requires 24h delay (two-step).
- Task 12d: Home-screen platform status widget (1h) — PlatformStatusWidget.jsx. Fits in Dashboard card grid. Only renders if strategy_registry has at least 1 row.
- Task 12e: Telegram notifications (0.5h) — src/notifications/platform_events.py. All notifications prefixed [RESEARCH]. Deduplication via hash for gate_ready events.

Selected Tier 7 (~3h):
- Task 11b.2: Correlation measurement (Spearman + Pearson + exceedance) — the 3 functions in src/platform/risk/correlation.py. Called daily + weekly by watch loop.
- Task 11b.3: Factor decomposition (Carhart 4 + QMJ) — src/platform/risk/factor_decomp.py. pandas-datareader pulls Ken French daily factors; cache locally since QMJ isn't on pandas-datareader (load from AQR CSV).
- Task 11b.5: PELT change detection — src/platform/risk/change_detection.py using ruptures library. Weekly batch.
- Task 11b.6: Tiered alerting — src/platform/risk/alerting.py with 60-min dedup. INFO/WARN/CRITICAL tiers.

Tier 8 (~3h):
- Task 2: Python plugin strategy interface — src/platform/strategy_plugin.py + src/platform/plugin_registry.py. Mostly interface definition; no plugins to load yet.
- Task 13: Docs sweep — MASTER.md Research Platform section (between Sections 8 and 9), RELEASES.md v0.24.0 entry, CHANGELOG.md, README.md badges, docs/platform/activation-guide.md (new — how to load a strategy).

Rules:
- Do NOT merge to main. Push to the feature branch only.
- Follow the 3× Ralph Loop protocol for EACH task (this is a big sprint — discipline matters more, not less).
- Run the full test suite before and after every major task. Pass count must not decrease.
- Frontend must build: cd frontend && npm run build
- Update MASTER.md and CHANGELOG.md/RELEASES.md with v0.24.0 (final, not alpha).
- Every commit atomic.
- Tag on merge: v0.24.0.
- Push to feature branch when complete:
  git push origin feat/platform-shadow

Non-negotiable quality gates:
1. test_harness_reconcile_uses_research_client passes — reconcile called with desk='research_xxx' routes to research Alpaca client, not swing.
2. test_harness_bracket_monitor_uses_research_client passes.
3. verify_accounts_distinct() raises if both desks configured to same paper account.
4. ShadowHarness.halt() closes ALL positions for THIS strategy only (not swing, not other research strategies).
5. /research-platform page renders with zero strategies (empty state) AND with 1+ strategies.
6. npm run build succeeds with no warnings escalated to errors.
7. Cost calibration script run on real DB produces slippage_bps within 30% of the hardcoded 3 bps (if it's wildly off, the calibration is wrong, not the hardcoded value).
8. Watch loop starts cleanly with strategy_registry empty (platform inert until strategies promoted).
9. All 85 existing shadow_trades rows still have desk='swing' after schema migrations.
10. SQL: SELECT * FROM shadow_trades WHERE desk != 'swing' returns 0 rows at merge time (platform inert at merge).

Specific implementation notes — the Alpaca call-site patch is the biggest risk:
- src/shadow_trading/alpaca_adapter.py: 12 internal calls to _get_trading_client() / _get_data_client() at lines 163, 184, 222, 277, 321, 340, 369, 390, 408, 440, 463, 485. MODIFY the 2 helpers to accept optional desk kwarg defaulting to current swing behavior. Internal calls unchanged.
- External callers get desk threaded through:
  - src/shadow_trading/executor.py:697 — add desk param to the function signature, default 'swing' for backward compat
  - src/shadow_trading/reconcile.py — ALL 3 entry points (reconcile_live_trades, reconcile_paper_trades, plus any helpers). This is ACTIVE code called from 4 scheduler paths. Threading MUST be correct.
  - src/shadow_trading/bracket_monitor.py — same
  - src/services/shadow_service.py — same
- Write a dedicated test test_reconcile_routes_by_desk that verifies: create a mock research position, call reconcile_paper_trades(desk='research_xxx'), verify get_client('research') was used not get_client('swing').

Repo-grep-verify before starting (this is the Pass 2 verification):
- grep -rn "_get_trading_client\|_get_data_client" src/ --include="*.py" | wc -l (expect ~16 lines total: 12 in alpaca_adapter + 4 external callers)
- grep -rn "reconcile_paper_trades\|reconcile_live_trades" src/scheduler/ src/cli/ --include="*.py" (confirm 4 call sites match what spec documents)
- grep -rn "@router\.\(get\|post\)" src/api/cloud_routes/ (confirm endpoint registration patterns haven't changed)

Ship order within this sprint (biggest-risk-first, so if time runs out you've shipped the critical stuff):
1. Task 7 (shadow harness + Alpaca patching) — HIGHEST RISK, ship first
2. Task 9 (watch loop integration) — MEDIUM risk
3. Task 12a/b/d/e (dashboard) — LOW risk but VISIBLE, valuable to ship for demo
4. Tier 7 tasks (correlation + factor decomp + PELT + alerting) — deferrable to v0.24.1 if time pressed
5. Tier 8 tasks (Python plugin + docs) — deferrable

If time runs out before Tier 7/8 complete: document clearly in the PR what shipped and what deferred. Platform is still usable without Tier 7 (correlation monitoring only matters when ≥2 strategies run concurrently, which is weeks away).

Push when complete. Open PR titled "v0.24.0: Strategy Research Platform — shadow harness + dashboard + correlation monitoring".

On merge, tag:
  git tag v0.24.0
  git push origin v0.24.0

Post-merge verification (manual, not automated):
1. SQL: SELECT COUNT(*) FROM strategy_registry — should be 0 (nothing promoted yet)
2. SQL: SELECT COUNT(*) FROM trials_registry — should be ≥1 if any backtest has run
3. curl /api/platform/strategies → returns empty list
4. Open dashboard /research-platform → renders empty state without errors
5. Verify watch loop logs show "[PLATFORM] No active research strategies" (expected when strategy_registry is empty)
```

---

# Summary of Sprint Structure

| Sprint | Branch | Scope | Hours | PR Title |
|---|---|---|---|---|
| 1 | `feat/platform-foundation` | Tier 1+2 (backtest + DSR + Lazy Prices spec + Task 0) | ~14h | v0.24.0-alpha1: Platform foundation + DSR gate |
| 2 | `feat/platform-rigor` | Tier 3 (CSCV + walk-forward + promotion + trials_registry) | ~8h | v0.24.0-alpha2: CSCV + walk-forward + promotion pipeline |
| 3 | `feat/platform-safety` | Tier 4 (defensive dashboard + hard exposure limits) | ~4h | v0.24.0-alpha3: defensive desk filtering + hard exposure limits |
| 4 | `feat/platform-shadow` | Tier 5+6+7+8 (shadow harness + dashboard + correlation + docs) | ~17h | v0.24.0: Strategy Research Platform |

**Total:** 43h minimum, 72h ambitious. Realistic weekend outcome: Sprints 1+2+3 = ~26h, Sprint 4 partial = v0.24.1 follow-up the next weekend.

**What "minimum viable platform" looks like after Sprint 1+2 only:**
- Backtest harness with DSR gate ✅
- Lazy Prices YAML spec ✅
- Promotion pipeline with trials_registry ✅
- CSCV + walk-forward ✅
- No shadow trading yet ❌ (Sprint 4)
- No dashboard platform page yet ❌ (Sprint 4)
- No correlation monitoring ❌ (Sprint 4)
- Still safe to run a backtest and see DSR-adjusted results ✅

**What "safe to activate a research strategy" requires:**
- Sprint 3 hard exposure limits ✅ (mandatory)
- Sprint 3 defensive desk filtering ✅ (mandatory)
- Sprint 4 shadow harness with reconcile desk threading ✅ (mandatory)

All three must land before any strategy gets promoted to `shadow_trading` status. This is encoded as a hard sequencing gate in the spec and in Sprint 3's and Sprint 4's gate criteria.
