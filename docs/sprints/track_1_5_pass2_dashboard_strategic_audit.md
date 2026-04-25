# Track 1.5 / B10b — Dashboard strategic audit (2026-04-25)

> Companion to `docs/sprints/track_1_5_pass2_dashboard_audit.md` (technical
> audit at commit 0380193). This document covers GAPS, REDUNDANCIES, and
> STRATEGIC-ALIGNMENT findings — what the dashboard *should* be doing that
> it isn't, and where it duplicates itself inconsistently.
>
> Round 7 covered broken routes, response-shape mismatches, mobile responsive,
> dark mode, and dead components. Those findings are NOT repeated here.

## Summary

- Gaps surfaced: **11**
- Redundancies surfaced: **5**
- Strategic-alignment findings: **6**

---

## A. Gaps (instrumentation that should exist but doesn't)

### G1: `broker_exceptions` — no dashboard surface at all

- **Source:** Track 1.5 / B2.A — `broker_exceptions` schema in `src/schema/registry.py`; logger at `src/shadow_trading/broker_exception_logger.py`
- **Current state:** Data written to DB table `broker_exceptions` by the executor and the exception logger. No API route exposes this table. `grep -rn "broker_exception" src/api/` returns zero matches.
- **Proposed surface:** New "Anomalies" card on the Dashboard hero (or a sub-section of the Health page), showing: exception count in last 7 days, count in last 24h, and a collapsible list of the 5 most recent entries with `ticker`, `operation`, `exception_type`, `recoverable` flag.
- **Cost estimate:** M (new API route + dashboard card, ~2h)
- **Priority:** should-have — operator cannot tell whether broker connectivity is degrading silently

### G2: `qty_mismatch_partial_fill` alert — no surface

- **Source:** Track 1.5 / B2.C — bounded retry logic in `src/shadow_trading/executor.py`; `qty_mismatch_partial_fill` status written on mismatch
- **Current state:** Status value exists in the trade lifecycle; the ShadowLedger and LiveLedger pages do not call out trades in this status separately. Health and Dashboard pages have no count card for it.
- **Proposed surface:** Badge or count on the LiveLedger or ShadowLedger page header ("N partial-fill mismatches in last 7d"). Optionally: a row in the existing "by exit reason" breakdown on TradeHistory.
- **Cost estimate:** S (surface existing status value in existing components, ~30m)
- **Priority:** should-have — partial fills silently corrupt P&L accounting

### G3: `instrumentation_version` distribution — operator cannot see if recent trades are fully instrumented

- **Source:** Track 1.5 / B5 — `instrumentation_version` column added to `shadow_trades`; `INSTRUMENTATION_VERSION_CURRENT = 3` defined at commit `ff69ad9`
- **Current state:** Column exists in DB. No frontend page reads or surfaces it. The Dashboard and TradeHistory pages never display it. The Stage-1 baseline analysis (T1.08) depends critically on this version gating, but the operator has no live view of "what fraction of recent trades are v3 (fully instrumented) vs v1/v2 (incomplete)".
- **Proposed surface:** A small "Instrumentation" stat on the TradeHistory or ShadowLedger summary row: "35/40 recent closed trades = v3 (fully instrumented)". Alternatively, a filter toggle on TradeHistory to show only v≥3 trades.
- **Cost estimate:** S (read existing column in existing queries, ~1h)
- **Priority:** should-have — without this the operator cannot confirm that the Stage-1 baseline computation is drawing from the correct pool

### G4: `llm_conviction_reason` text — nowhere to read it on the dashboard

- **Source:** Track 1.5 / B4 — `llm_conviction_reason` persisted to `shadow_trades` at open-path
- **Current state:** Column written to DB by executor. TradeHistory's `RecentTradesTable` shows `exit_reason` but does not show `llm_conviction_reason`. The ShadowLedger expandable row component (`ExpandableTradeRow`) also omits it. No read surface exists anywhere.
- **Proposed surface:** An expandable detail row in TradeHistory and ShadowLedger showing `llm_conviction_reason` as a quoted text block (similar to how `thesis_text` is shown in Packets).
- **Cost estimate:** S (add field to expandable row rendering, ~1h)
- **Priority:** should-have — this was the primary rationale for B4 ("where can operator read the LLM's reasoning for a trade?")

### G5: "Approaching timeout" count — no aggregate surface

- **Source:** Track 1.5 / B9 — `timeout_status` computed by `shadow_service._compute_timeout_status`; `TimeoutCell` component renders per-trade progress
- **Current state:** The `TimeoutCell` component exists and renders on ShadowLedger, LiveLedger, and TradeHistory tables (per-trade level). There is no aggregate count of "N trades currently approaching timeout" on the Dashboard hero or Health page. The operator must scan the table row-by-row.
- **Proposed surface:** A MetricCard on the Dashboard (below the system status cards) showing "N approaching timeout" with amber coloring when N > 0. Computed from `openTrades` data that is already fetched.
- **Cost estimate:** S (derive from existing `openTrades` query in Dashboard.jsx, ~30m)
- **Priority:** should-have — operator's stated concern was spotting approaching timeouts at a glance

### G6: Stage-1 OOS trade count toward Stage-2 evaluation gate — not surfaced

- **Source:** `SHIPPED.md` §Deferred — "Stage 2 evaluation requires 150 OOS trades (~3 months of live trading)"; T2.04 promotion gate (≥4-of-5 vote)
- **Current state:** The CTOReport `Phase 1 Gate Progress` bar shows `X/50 trades` — that is the Phase-1 training gate, not the Stage-2 evaluation gate. The Dashboard hero `BuildScoreHero` shows `phase.trades_closed / phase.trades_required` but this also tracks against the training target, not the 150-trade OOS evaluation target. No surface shows "we are at X/150 toward Stage-2 eligibility".
- **Proposed surface:** A second progress bar on the CTOReport or Dashboard labeled "Stage-2 evaluation: X/150 OOS trades" alongside the existing Phase-1 bar. This is purely a count from `shadow_trades` — no new computation needed.
- **Cost estimate:** S (extend existing progress bar block in CTOReport.jsx, ~1h)
- **Priority:** should-have — the operator's most important medium-term milestone has no visible countdown

### G7: Stage-2 promotion gate outputs (T2.04) — no wiring path exists

- **Source:** `src/methods/promotion_gate.py` — ≥4-of-5 voting gate (PSR/DSR/MinTRL/CPCV/block-bootstrap). Currently shelf. No API route, no dashboard surface.
- **Current state:** The module exists and is tested. When the gate is eventually run (manually or via script), its result (vote tally, per-method pass/fail, MinTRL, p-values) is returned as a Python dict but has no persistent storage and no API endpoint.
- **Proposed surface:** A "Promotion Gate" panel on the WalkforwardResults or Strategy page showing the last-run gate output: vote count, method-by-method results, timestamp. Requires (a) a storage table for gate results and (b) an API route. This is a future-need item but should be tracked now so the design is ready when Stage-2 eligibility approaches.
- **Cost estimate:** L (new schema table + API route + dashboard panel)
- **Priority:** nice-to-have now, should-have when Stage-2 eligibility is ~1 month away

### G8: Devil's-advocate check paper trail — no dashboard echo

- **Source:** T3.01 — `audits/2026-04-27/devils_advocate_stage1.md` documents 5 bias categories, each with a SQL check to run before signing
- **Current state:** The devil's-advocate doc exists as a markdown file. Whether the five checks (selection bias, look-ahead, cost mismodel, regime shift, survivorship) have been run — and what their outcomes were — is not visible anywhere on the dashboard. The Validation page shows walkforward validation runs; there is no "bias checks" surface.
- **Proposed surface:** A "Bias Checks" section on the Validation or Strategy page listing the five T3.01 categories with a checkbox-style status: "run / not run / failed". Could be a lightweight notes-table that the operator updates manually after each baseline recompute.
- **Cost estimate:** M (new lightweight table in schema + simple status widget)
- **Priority:** nice-to-have — the DA doc is already the paper trail; this adds a living checklist view

### G9: Cost-calibration data (`cost_calibration.json`) — written to file, not surfaced

- **Source:** Track 2 Cohort 3 Half A / T2.07 — `src/cost_model/calibration.py` writes `C:/arcis/data/cost_calibration.json` after reading `shadow_trades`
- **Current state:** The file is written to disk by `calibrate_from_shadow_trades()`. No API route reads the file. No dashboard page surfaces the calibration results (median entry slippage bps, median exit slippage bps, round-trip cost, N trades contributing).
- **Proposed surface:** A small card on the CTOReport or Strategy page showing "Cost model last calibrated: <date>, entry slippage: Xbps, exit slippage: Ybps, N=Z trades". The devil's-advocate §3 (cost mismodel) check maps directly to this.
- **Cost estimate:** S (add a `/cost-calibration` route that reads the JSON file + a MetricCard block, ~1h)
- **Priority:** nice-to-have during Stage-1; should-have before any Stage-2 baseline is signed

### G10: Point-in-time universe (T2.09) — no surface

- **Source:** Track 2 Cohort 3 Half A / T2.09 — `src/universe/pit.py` provides `get_sp100_at(as_of_date)` but 24 callers still use the survivorship-biased `get_sp100_universe()` per `SHIPPED.md`
- **Current state:** No dashboard page shows (a) whether PIT universe is being used or (b) the migration count (0/24 callers migrated). The devil's-advocate §5 (survivorship bias) maps directly to this.
- **Proposed surface:** A note on the Architecture or Strategy page: "Universe bias status: X/24 callers migrated to PIT". This could be a simple static counter updated each sprint rather than a live API call.
- **Cost estimate:** S (static text block initially; live counter is M)
- **Priority:** nice-to-have — bias risk is documented; visibility reduces the chance it is forgotten

### G11: Methodology toolkit outputs — none surfaced

- **Source:** Track 2 Cohort 2 — `src/methods/` (CPCV, block bootstrap, MC permutation, White RC, PSR/DSR/MinTRL)
- **Current state:** All five methods are shelf (no production caller). When the operator or a developer runs them manually, results are returned as Python dicts and discarded. No storage, no API, no dashboard. The WalkforwardResults page shows the legacy walkforward runner output but has no concept of the new methodology toolkit.
- **Proposed surface:** A "Methodology Results" panel on WalkforwardResults or a new "Research" sub-page, showing the last run of each method with timestamp and pass/fail. Prerequisite: a `methodology_run_log` table in the schema to persist results.
- **Cost estimate:** L (new schema table + 5 API sub-routes + dashboard panel)
- **Priority:** nice-to-have — these methods are shelf; surface becomes critical at Stage-2 gate

---

## B. Redundancies (same metric in inconsistent places)

### R1: Sharpe ratio — four surfaces, three formulas

- **Locations:**
  1. `Dashboard.jsx:413` — `kpis.sharpe_ratio` from `ctoData.headline_kpis` (backend: `_compute_trade_summary` in `cloud_routes/analytics.py:181`) — raw mean/stdev, no rf adjustment, annualized against sample (no sqrt(N_per_year) — just mean/stdev with no scale factor applied)
  2. `CTOReport.jsx:120` — same `sharpe_ratio` from the same CTO route — identical to #1
  3. `ModelPerformance.jsx:100` — `am.sharpe_ratio` from the model-performance endpoint — formula not confirmed canonical
  4. `TradeHistory.jsx:107` — `rollingSharpe()` computed client-side: `mean/std * sqrt(150)` (annualized with 150 trades/yr assumption, raw pnl_pct, NO rf adjustment)
  5. `TradeHistory.jsx:352-355` — `attribution.excess_sharpe` from the sharpe-attribution endpoint (`cloud_routes/trades.py:60-117`) — rf-adjusted excess Sharpe, the one canonical value per T1.03

- **Inconsistency:**
  - The canonical formula per T1.03 is rf-adjusted excess Sharpe (`src/analytics/canonical_sharpe.py`). The sharpe-attribution endpoint (`/api/shadow/sharpe-attribution`) uses a helper `_sharpe_with_se` that returns raw Sharpe of excess-return values — correctly constructed but NOT calling `canonical_sharpe.py`.
  - The CTO report endpoint (`cloud_routes/analytics.py:177-181`) uses a bare `mean / stdev` formula with no rf adjustment and no annualization factor — this is neither canonical nor consistent.
  - The client-side `rollingSharpe()` in TradeHistory applies `sqrt(150)` for annualization but uses raw pnl_pct (no rf subtraction).
  - The Dashboard hero shows the CTO-route Sharpe (uncanonical); the TradeHistory "primary metric" panel shows the attribution Sharpe (closer to canonical). An operator looking at both pages will see different numbers for the same strategy.

- **Proposed fix:** All API routes computing Sharpe should call `src.analytics.canonical_sharpe` and return a field named `rf_adjusted_excess_sharpe` consistently. The CTO route's `sharpe_ratio` field should either be deprecated in favour of the canonical value or clearly labeled "raw (diagnostic)". The Dashboard hero should be updated to display the canonical excess Sharpe from the attribution endpoint rather than the CTO-route value.
- **Priority:** urgent — this metric drives the Stage-1 and Stage-2 decision gates

### R2: Win rate — three surfaces, one possibly unfiltered

- **Locations:**
  1. `Dashboard.jsx:469` — `closedData.metrics.win_rate` from `shadow_service.get_shadow_history()` — computed by `compute_shadow_metrics()` in `src/shadow_trading/metrics.py`. This function receives the `closed` list from `get_closed_shadow_trades()` which calls `store.py` with `COALESCE(quarantined, 0) = 0` — quarantine filter applied.
  2. `Dashboard.jsx:469` fallback — `accountData.win_rate` from Alpaca account info — origin is Alpaca API, denominator unknown, quarantine filter definitely NOT applied.
  3. `CTOReport.jsx:197` / `TradeHistory.jsx:447` — `kpis.win_rate` from CTO route — computed in `cloud_routes/analytics.py:195` against `closed_recent` which is filtered by `COALESCE(quarantined, 0) = 0`.
  4. `ModelPerformance.jsx:98` — `am.win_rate` per model version from the model-performance endpoint — denominator and quarantine filter status unconfirmed.

- **Inconsistency:** The Dashboard has a silent fallback path to `accountData.win_rate` (from Alpaca) when `closedData.metrics.win_rate` is null. The Alpaca-sourced value includes ALL closed positions (not just shadow trades, and definitely not quarantine-filtered). The operator may unknowingly see the Alpaca win rate, which is meaningless for strategy evaluation. The `metrics.py` win rate uses pnl_dollars thresholding (`pnl > 0`) whereas the CTO route uses pnl_pct — these diverge on trades where one is positive and the other is zero-or-negative due to rounding.
- **Proposed fix:** Remove the Alpaca-sourced fallback from the Dashboard. Standardize on a single denominator (closed shadow trades, quarantine-filtered, instrumentation_version >= 3 when applicable). Add a denominator note ("N=35 fully-instrumented") next to every win-rate display.
- **Priority:** urgent — the Stage-1 baseline win rate (69%) is a key signed figure; inconsistent surfaces mislead the operator

### R3: P&L — five surfaces, quarantine filter applied inconsistently

- **Locations:**
  1. `Dashboard.jsx:286-287` — cumulative P&L chart computed client-side from `closedData.trades` — these trades come from `shadow_service.get_shadow_history()` which calls `get_closed_shadow_trades()` with quarantine filter applied.
  2. `Dashboard.jsx:467` — `Shadow Equity` MetricCard using `accountData.equity` from Alpaca — no quarantine filter (Alpaca has no concept of quarantine).
  3. `ShadowLedger.jsx:273` — `totalPnl` computed client-side from the ShadowLedger closed trades — quarantine filter depends on the underlying query.
  4. `TradeHistory.jsx:452` — `all.pnl` computed client-side — from `get_closed_shadow_trades(180)` via shadow_service — quarantine filter applied.
  5. `CTOReport.jsx:228` — `ts.total_pnl` from CTO route — quarantine filter applied in cloud route.

- **Inconsistency:** The Shadow Equity path (#2) uses Alpaca account equity (real paper account balance), which includes trades that may not be in the `shadow_trades` DB at all (orphaned IB positions, corrections). All other paths use `shadow_trades` with quarantine filter. The operator sees equity from #2 as the headline on the Dashboard but P&L from #1 as the cumulative chart — these will diverge whenever Alpaca has trades not tracked in shadow_trades.
- **Proposed fix:** Pick one canonical P&L surface (shadow_trades + quarantine filter) and make it explicit. Label the Alpaca equity card "Alpaca Paper Balance" (not "Shadow Equity") to distinguish it from the computed shadow P&L. Add a reconciliation delta ("Shadow P&L vs Alpaca balance: +$X gap") as a single diagnostic row.
- **Priority:** important — confusing during Mon's live deploy phase when small discrepancies will appear

### R4: Trade count — four surfaces with different denominators

- **Locations:**
  1. `Dashboard.jsx:306` — `closedCount = ts.trades_closed || accountData.total_closed || 0` — same silent fallback issue as win rate (accountData from Alpaca is different from DB count)
  2. `CTOReport.jsx:166-169` — `Phase 1 Gate Progress` bar uses `tradesClosed/50` from the CTO route — quarantine-filtered, but no instrumentation_version filter
  3. `ShadowLedger.jsx` — counts from the shadow ledger query, quarantine-filtered
  4. `Health.jsx` — the Health page uses build-score data which counts `trades_closed` from the CTO route's `phase_progress`

- **Inconsistency:** The `trades_closed` figure used in the Phase-1 gate progress bar (50-trade target) is not filtered to `instrumentation_version >= 3`. The Stage-1 baseline memo used N=35 (fully-instrumented filter applied). An operator watching the CTOReport progress bar will see "40 trades" but the baseline analysis would use only "35 trades" — the discrepancy is never explained on-screen.
- **Proposed fix:** Add a parenthetical to the Phase-1 progress bar: "40 total closed (35 fully-instrumented)". Deprecate the Alpaca-sourced `accountData.total_closed` fallback in Dashboard.jsx.
- **Priority:** important — the 50-trade threshold drives a decision gate

### R5: Exit reason breakdown — two surfaces, different groupings

- **Locations:**
  1. `TradeHistory.jsx:265-274` — `exitReasonBreakdown` computed client-side from raw `exit_reason` values, grouped by exact string, showing count + total_pnl + avg_pnl
  2. `CTOReport.jsx:249-258` — `data.by_exit_reason` from the CTO API endpoint — same column, but grouping may differ if the backend normalizes values vs the frontend using raw strings

- **Inconsistency:** The Track 1.5 / B3 taxonomy (`src/shadow_trading/exit_reason.py`) canonicalized exit reasons via `coerce_exit_reason()`. If historical trades have non-canonical values that were not backfilled, the client-side grouping in TradeHistory will show them as separate buckets while the API-side grouping may or may not have coerced them. The `1a5e4d6` commit ("route 9 remaining exit_reason writers through coerce") suggests some legacy values may still exist uncoerced.
- **Proposed fix:** Confirm that the CTO route's `by_exit_reason` aggregation applies `coerce_exit_reason()` server-side before grouping, so both surfaces use the canonical taxonomy. If not, add the normalization in the API layer.
- **Priority:** lower — cosmetic inconsistency, but misleading if debugging exit-reason performance differences

---

## C. Strategic-alignment findings

### S1: Primary KPI is ambiguous — "Sharpe ratio" on Dashboard hero is not the canonical decision metric

- **Question the operator needs to answer in <5 seconds:** "Is the strategy generating alpha over SPY beta, or just riding the bull market?"
- **Current dashboard surface:** The Dashboard hero shows `kpis.sharpe_ratio` (uncanonical, from CTO route — see R1). This is the raw Sharpe with no rf adjustment and no SPY benchmark. The canonical answer to the question is the `excess_sharpe` from the attribution endpoint, which is only visible on the TradeHistory page's "Primary Metric: Excess-Return Sharpe (vs SPY)" panel (labeled `SD#41 REVISED`).
- **Gap:** The operator's most important question ("are we generating alpha or beta?") requires navigating to a secondary page. The Dashboard hero shows a number that the Stage-1 memo explicitly warns is insufficient (SPY-relative p-value = 0.43, not significant). The word "Sharpe ratio" on the hero gives no signal about which formula is being used.
- **Proposed:** Swap the Dashboard hero Sharpe card to show `excess_sharpe` from the attribution endpoint with a tooltip explaining it is vs SPY. Add a secondary subtext showing the t-stat and the IB gate threshold (t >= 2.0 at 150 OOS trades). If the attribution endpoint fails, fall back gracefully to the CTO Sharpe labeled explicitly as "raw (no SPY adj)".

### S2: Halt criteria from Decision Matrix — operator cannot see "how close are we to Halt?"

- **Question:** "Are we operating inside the safe zone of the §3.1 Decision Matrix, or approaching a threshold that would trigger Halt?"
- **Current dashboard surface:** The Dashboard has a HALT TRADING button (binary: halted or not). There is no surface showing the quantitative thresholds from §3.1: e.g., the CI lower bound threshold (≥ -0.2) or the rolling t-stat (≥ +1.5). The operator knows the current Sharpe point estimate but not how far the CI lower bound is from the halt threshold.
- **Gap:** The signed Stage-1 baseline (CI lower bound: [0.1113, 2.2276] per the memo) is not echoed anywhere on the dashboard. If live trading degrades performance, the operator has no at-a-glance view of "CI lower = X, threshold = -0.2, distance = Y".
- **Proposed:** A "Decision Matrix Status" widget on the Dashboard or CTOReport showing:
  - Current CI lower bound (from attribution endpoint, recomputed periodically)
  - Stage-1 signed CI lower bound (static anchor from memo: +0.1113)
  - §3.1 halt threshold: CI lower ≥ -0.2
  - Distance to Halt: (+0.1113 - (-0.2)) = 0.31 currently, shrinks as performance decays

### S3: Risk governor cap remaining — not surfaced

- **Question:** "How much of the position cap have I consumed, and how much head room do I have before the governor blocks new trades?"
- **Current dashboard surface:** The dashboard shows "Open Trades" count and the HALT button, but no surface shows the `effective_position_cap` value from `src/risk/governor.py` or how many dollars are currently deployed against that cap.
- **Gap:** T1.04 reconciled the cap across 4 namespaces. The operator cannot see the result of that reconciliation on-screen. If the cap is $100 and $85 is deployed, the operator does not know new trades will be blocked until they try to scan and the governor raises.
- **Proposed:** Add a "Governor" row to the Dashboard system status cards: "Cap: $X | Deployed: $Y | Available: $Z". The cap is read from config; deployed is the sum of `planned_shares * entry_price` across open trades. This is computable from data already fetched by the Dashboard.

### S4: Mon's preflight gate output — no dashboard echo

- **Question:** "Did this morning's preflight pass, and on which items?"
- **Current dashboard surface:** None. The preflight script (`scripts/preflight_monday.py`) writes a transcript to `audits/2026-04-27/preflight_transcript.txt` on disk. This file is not indexed, not served by any API route, and not visible on the dashboard.
- **Gap:** The operator runs preflight at 9:30 AM ET before markets open. If preflight passes, they deploy. If any check fails, they hold or halt. Currently the only way to see preflight status after the fact is to SSH in and read the transcript file. There is no dashboard echo of "last preflight: <timestamp>, result: PASS/FAIL, items: 10/10 passed".
- **Proposed:** A lightweight API route that reads `preflight_transcript.txt` and returns the summary (timestamp + pass/fail per item). Surface as a collapsible card on the Dashboard, similar to the existing `AuditChip` component. This is a read-only file operation — low risk.
- **Cost estimate:** S (new route reads file, existing chip pattern in Dashboard)

### S5: Stage-1 signed memo numbers — not anchored on dashboard

- **Question:** "What were the signed Stage-1 numbers, and how does current performance compare to them?"
- **Current dashboard surface:** The Stage-1 signed memo is a markdown file at `audits/2026-04-27/stage1_baseline_memo.md` in git. There is no surface on the dashboard that shows the signed values as an anchor:
  - N fully-instrumented: 35
  - rf_adjusted_excess_sharpe: 6.1379
  - 95% CI lower: 0.1113
  - p-value: 0.0302
  - SPY-relative p-value: 0.4326 (not significant)
- **Gap:** As new trades accumulate, the operator has no way to see on the dashboard "signed baseline was X, current recompute is Y, delta is Z". The Stage-1 memo is the reference point for the §3.1 Decision Matrix, but it exists only in git history.
- **Proposed:** A "Stage-1 Anchor" widget on the CTOReport or TradeHistory page showing the signed values alongside the current recomputed values. The anchor values are static (from the memo); the current values come from the attribution and sharpe endpoints. This is a read-only display — no recomputation needed.

### S6: Block-bootstrap CI still pending — dashboard shows IID CI as if it were final

- **Question:** "Are the confidence intervals I'm seeing conservative or optimistic?"
- **Current dashboard surface:** The TradeHistory "Excess-Return Sharpe" panel shows `excess_sharpe_ci_low` and `excess_sharpe_ci_high`. These CIs come from the attribution endpoint which uses a normal-approximation CI (`excess_sr ± 1.96 * se`), not the block bootstrap. The Stage-1 memo explicitly warns: "IID bootstrap is acknowledged optimistic; T2.02 block-bootstrap rerun is the Track-2 follow-up."
- **Gap:** The dashboard presents CIs with no caveat about methodology. An operator who has not read the memo cannot tell whether the CI is block-bootstrapped (conservative) or IID-approximated (optimistic). The `block_bootstrap` module (T2.02) was delivered in Track 2 Cohort 2 and is shelf — but it is never called by the attribution endpoint.
- **Proposed:** Add a footnote to the Excess-Sharpe panel: "CI: normal approx (IID assumption — optimistic). Block-bootstrap rerun pending." This is a one-line text change. The longer-term fix is wiring T2.02 into the attribution endpoint, but the label is a 5-minute fix that sets correct operator expectations.

---

## Recommended Round 8b dispatch shape

After operator triage of both the Round 7 technical audit (R8-A through R8-M) and this strategic audit, suggested fix-task groupings for Round 8:

| ID | Scope | Findings addressed | Effort |
|---|---|---|---|
| R8b-1 | Canonicalize Sharpe on Dashboard hero — swap `kpis.sharpe_ratio` for attribution `excess_sharpe`; add t-stat subtext | R1, S1 | M — 2–3h (API + frontend) |
| R8b-2 | Add `broker_exceptions` API route + Dashboard "Anomalies" card | G1 | M — 2h |
| R8b-3 | Surface `instrumentation_version` distribution in TradeHistory summary | G3 | S — 1h |
| R8b-4 | Add `llm_conviction_reason` to expandable row in TradeHistory and ShadowLedger | G4 | S — 1h |
| R8b-5 | Add "approaching timeout" count card to Dashboard (from existing openTrades query) | G5 | S — 30m |
| R8b-6 | Add Stage-2 evaluation progress bar to CTOReport (X/150 OOS trades) | G6 | S — 1h |
| R8b-7 | Remove Alpaca-sourced win_rate/trade_count fallbacks from Dashboard; add denominator labels | R2, R4 | S — 1h |
| R8b-8 | Label "Shadow Equity" card as "Alpaca Paper Balance" and add reconciliation delta | R3 | S — 30m |
| R8b-9 | Add Decision Matrix Status widget (CI lower, halt threshold, distance to Halt) | S2 | M — 2–3h (new API endpoint + widget) |
| R8b-10 | Add Governor cap remaining to Dashboard system status cards | S3 | S — 1h (config read + open-position sum) |
| R8b-11 | Preflight echo: new API route reading transcript + Dashboard AuditChip-style card | S4 | S — 1–2h |
| R8b-12 | Stage-1 anchor widget on CTOReport: signed values vs current recompute | S5 | S — 1h (static anchor + live query) |
| R8b-13 | Add "CI: IID approximation — optimistic" footnote to TradeHistory Excess-Sharpe panel | S6 | S — 5m text change |
| R8b-14 | Add cost-calibration surface (route reading cost_calibration.json + CTOReport card) | G9 | S — 1h |
| Defer | Surface qty_mismatch_partial_fill in ShadowLedger (G2) | G2 | S — blocked on confirming status value propagation |
| Defer | Promotion gate panel on WalkforwardResults (G7) | G7 | L — blocked on schema + storage design |
| Defer | Methodology toolkit results panel (G11) | G11 | L — blocked on schema + storage design |
| Defer | PIT universe migration counter (G10) | G10 | S — low urgency until migration planned |
| Defer | Devil's-advocate paper trail surface (G8) | G8 | M — design depends on operator preference for notes vs structured table |

**Operator triage guidance:** R8b-1 (canonical Sharpe hero), R8b-2 (broker_exceptions surface), R8b-9 (Decision Matrix status), and R8b-13 (CI footnote) are the highest-signal items relative to effort. They close the gap between what the dashboard shows and what the operator needs to make the daily "continue trading / halt" decision. The remaining items are incremental instrumentation improvements that can be batched.
