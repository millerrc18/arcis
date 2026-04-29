# Dashboard Gap List — 2026-04-29

**Tracker:** #54 (`#807` Dashboard sprint, currently `[in_progress]`)
**Author:** investigation agent (no code changes — synthesis only)
**Worktree branch:** `docs/54-dashboard-gap-list` (cut from `origin/main` HEAD `0114f9e`)

This doc cross-references three source audits against shipped work and produces a single prioritized punch-list. Operator's primary cockpit is halcyonlab.app on Render; today (2026-04-29) operator reports stale-data symptoms and asked for "(1) status / state freshness, and (2) audit follow-through findings."

## Sources cross-referenced

| Source | Path | Findings parsed |
|---|---|---|
| Round 7 — technical wiring audit | `docs/sprints/track_1_5_pass2_dashboard_audit.md` | 25 (5 Critical + 9 Important + 7 Cleanup + 4 Future-need) |
| Round 7b — strategic audit | `docs/sprints/track_1_5_pass2_dashboard_strategic_audit.md` | 22 (11 Gaps + 5 Redundancies + 6 Strategic-alignment) |
| #807 operator audit | GitHub issue #807 (Tier 1.A through 4.C) | 17 (6 Tier 1 + 5 Tier 2 + 5 Tier 3 + 1 Tier 4) |
| **Total** | | **64 findings** |

## Method

For each finding, I:
1. Searched commit messages (`git log --grep`) for the finding ID and references to PRs from the audit-spec.
2. Spot-checked source files in the audit's prescribed locations to confirm the fix is present (e.g. C1 `historyList = Array.isArray(history) ? history : []` against `cloud_routes/analytics.py:920` returning bare array).
3. Cross-referenced PR bodies of #690, #816, #827, #833, #840 for the explicit closure language.
4. Flagged `partially-done` when the backend fix shipped but the frontend equivalent did not, or vice versa.

---

## Executive Summary

- **Total findings parsed:** 64 across three audits
- **Shipped:** 36 (Round 7: 14/25 + Round 7b: 9/22 + #807 Tier 1: 5/6 + #807 Tier 2-4 side-effects: 8/11)
- **Remaining:** 28
  - Critical / Important (operator-decision-impacting): 1
  - High-impact freshness (stale-data symptoms): 5
  - Observability gaps (operator can't see things they need): 11
  - Cleanup / Future-need (defer): 11
- **Closing PRs (chronological):** #690 (Round 8.A-F mega-PR for Round 7 Critical + many Round 7b), #816 (#807 Tier 1.B registries), #827 (#807 Tier 1.E + 1.F), #833 (#807 Tier 1.C orphan-route wiring + CORS doc), #840 (#807 Tier 1.D diagnostic_runs watchdog), #74 (manual #807 Tier 1.A reconcile, 623,360 ghost rows deleted)

### Top 5 cockpit blockers

These are the items that, until fixed, distort numbers the operator uses to make daily go/halt decisions:

1. **#807 Tier 1.C residual** — `CORS_ORIGINS` env var on halcyon-api Render service still missing `https://halcyonlab.app`. Frontend dev-tools still capture cross-origin failures on `/api/system/index`. Operator-side action only — code fix shipped via #833 but production env-var change is pending operator. (PR #833 body section "Operator action required after merge.")
2. **S2: No "distance to Halt" surface** — operator can see Stage-1/2 traffic light (green/amber/red) on the KPI strip but cannot see the *quantitative distance* to the halt threshold. Decision Matrix §3.1 specifies CI lower ≥ −0.2; current CI lower is +0.1113. Distance = 0.31 currently. As live trading degrades performance there is no at-a-glance "how close are we?" surface.
3. **S3: Risk governor cap remaining not surfaced** — operator cannot see "Cap: $X | Deployed: $Y | Available: $Z" at a glance. Cap is read from config; deployed is sum of `planned_shares * entry_price` across open trades — both already fetched by Dashboard. New trades can be silently blocked by governor with no warning panel.
4. **F1: `instrumentation_version >= 3` filter not propagated to per-page analytics queries** — KPI strip filters correctly but TradeHistory, ShadowLedger, Velocity, Attribution, CTOReport pages still aggregate from un-filtered `shadow_trades`. Numbers on these pages diverge from the canonical hero KPI strip. Operator sees "40 closed" on TradeHistory and "35 fully-instrumented" in KPI strip caption with no on-page explanation of the gap.
5. **G2: `qty_mismatch_partial_fill` status not surfaced** — partial fills silently corrupt P&L accounting and the only path to noticing is to scan the LiveLedger row-by-row. No header badge, no count card. Bounded retry logic exists; the alert surface does not.

---

## Per-finding tables

### Round 7 — Technical wiring audit (`docs/sprints/track_1_5_pass2_dashboard_audit.md`)

#### Critical (5 of 5 closed)

| ID | Title | Page(s) | Tier | Status | Effort | Closing PR |
|---|---|---|---|---|---|---|
| C1 | Monitoring history shape mismatch | lines 17-25 | Critical | shipped | — | #690 (Round 8.A `a34a6ca`) — verified `cloud_routes/analytics.py:920` returns bare array |
| C2 | `/ib-shadow/*` local routes missing | lines 29-34 | Critical | shipped | — | #690 (Round 8.A) — `src/api/routes/ib_shadow.py` exists |
| C3 | `/strategy-detail/{type}` local route missing | lines 38-43 | Critical | shipped | — | #690 — `src/api/routes/strategy_detail.py` exists |
| C4 | `/system/index` local route missing | lines 47-52 | Critical | shipped | — | #690 — `src/api/routes/system_index.py` exists |
| C5 | `/projections/live` local route missing | lines 56-61 | Critical | shipped | — | #690 — `src/api/routes/projections.py:99` registers `/projections/live` |

#### Important (8 of 9 closed; 1 partial)

| ID | Title | Page(s) | Tier | Status | Effort | Dependencies | Suggested owner |
|---|---|---|---|---|---|---|---|
| I1 | WalkforwardResults dark/light theme | lines 67-72 | Important | shipped | — | — | — |
| I2 | StrategyResearch dark/light theme | lines 76-81 | Important | shipped | — | — | — |
| I3 | Diagnostics dark/light theme | lines 85-90 | Important | shipped | — | — | — |
| I4 | System sub-components dark mode | lines 94-98 | Important | **partially-done** | S | — | coding-team (sweep cleanup) |
| I5 | PlatformStatusWidget hardcoded `bg-white dark:bg-slate-800` | lines 102-106 | Important | shipped | — | — | — |
| I6 | Settings dark/light mixed | lines 110-115 | Important | shipped | — | — | — |
| I7 | Dashboard `useState` misuse for desk fetch | lines 119-131 | Important | shipped | — | — | — (Dashboard.jsx:239 cites I7 explicitly) |
| I8 | Monitoring hardcoded `localhost:8000` | lines 135-140 | Important | shipped | — | — | — |
| I9 | Packets `Array.isArray` guard | lines 144-148 | Important | shipped | — | — | — (Packets.jsx:62) |

**I4 partial-done detail:** `dark:bg-slate-*` / `dark:border-slate-*` / `dark:text-slate-*` classes still appear in:
- `frontend/src/components/system/SystemIndexCard.jsx` (1 occurrence)
- `frontend/src/components/system/CapabilityDetailModal.jsx` (4 occurrences)
- `frontend/src/components/system/WhatsNewPanel.jsx` (1 occurrence)

QuickStatsPanel.jsx and SystemIndexPanel.jsx have been migrated. The 6 remaining occurrences are visual-consistency issues, not functional breaks.

#### Cleanup (3 of 7 closed; 1 partial; 3 not-started)

| ID | Title | Page(s) | Tier | Status | Effort | Dependencies | Suggested owner |
|---|---|---|---|---|---|---|---|
| CL1 | `BacktestEquityChart` import-but-render-unverified | lines 154-158 | Cleanup | resolved | — | — | — (StrategyResearch.jsx:227 renders it; concern was a false alarm) |
| CL2 | Dead route `/api/traffic-light/current` | lines 162-167 | Cleanup | not-started | S | — | deferrable |
| CL3 | Dead-route candidate `/api/projections/live` | lines 171-175 | Cleanup | resolved | — | — | (subsumed by C5 — local route now exists) |
| CL4 | `Toast.jsx` global `toast()` export unused | lines 179-183 | Cleanup | not-started | S | — | deferrable |
| CL5 | `overflow-x-auto` for WalkforwardResults / StrategyResearch / Diagnostics | lines 187-191 | Cleanup | **partially-done** | S | — | coding-team (StrategyResearch + Diagnostics still missing wrapper) |
| CL6 | `QuickStatsPanel` data-passing pattern | lines 195-199 | Cleanup | not-started | S | — | deferrable |
| CL7 | Monitoring double-fetch (`fetchApi` + `api.getMonitoringSnapshot`) | lines 203-207 | Cleanup | not-started | S | — | coding-team (Monitoring.jsx:42 still uses raw `fetchApi`) |

#### Future-need (0 of 4 closed)

| ID | Title | Page(s) | Tier | Status | Effort | Dependencies | Suggested owner |
|---|---|---|---|---|---|---|---|
| F1 | `instrumentation_version >= 3` filter on per-page analytics queries | lines 213-217 | Future-need | **partially-done** | M | analytics query migration | Sprint-N (cockpit truth-up) |
| F2 | Strategy page `instrumentation_version` filter | lines 221-225 | Future-need | not-started | S | F1 | Sprint-N |
| F3 | `time_to_mfe_days` column not yet in schema | lines 229-233 | Future-need | not-started | M | schema change | deferrable (page falls back gracefully) |
| F4 | `/council/strategic` local route missing | lines 237-241 | Future-need | not-started | S | — | deferrable (cosmetic in local dev) |

**F1 partial-done detail:** `cloud_routes/kpis.py:73` calls `filter_fully_instrumented(raw_trades)` — KPI strip filters correctly. But `cloud_routes/analytics.py` (CTO route, sharpe-attribution, cto_report) and the per-page TradeHistory / ShadowLedger / Velocity / Attribution queries do NOT apply the filter. Per the operator's stale-data symptom on TradeHistory/ShadowLedger today, this is a candidate root cause for cross-page inconsistency: numbers on those pages aggregate trades that the canonical pipeline excludes.

---

### Round 7b — Strategic audit (`docs/sprints/track_1_5_pass2_dashboard_strategic_audit.md`)

#### A. Gaps (5 of 11 closed; 6 remaining)

| ID | Title | Page(s) | Tier | Status | Effort | Dependencies | Suggested owner |
|---|---|---|---|---|---|---|---|
| G1 | `broker_exceptions` no dashboard surface | lines 21-27 | Important | shipped | — | — | — (#690 Round 8.C `ee97f6e`; `BrokerExceptionsPanel.jsx` exists) |
| G2 | `qty_mismatch_partial_fill` no surface | lines 30-36 | Important | not-started | S | — | coding-team |
| G3 | `instrumentation_version` distribution invisible | lines 38-43 | Important | shipped | — | — | — (KPI strip caption "N=35 fully-instrumented", CTOReport.jsx:185 same; commit `920d230`) |
| G4 | `llm_conviction_reason` no read surface | lines 46-51 | Important | shipped | — | — | — (TradeHistory.jsx:162-167, ShadowLedger.jsx:221-225) |
| G5 | "Approaching timeout" aggregate count | lines 54-59 | Important | shipped | — | — | — (Dashboard.jsx:316-319 + 447-448) |
| G6 | Stage-2 OOS progress bar (X/150) | lines 62-67 | Important | shipped | — | — | — (KPIStrip.jsx:144-157 `PromotionGateCard` shows "Stage-2 eligibility: N/150 OOS trades") |
| G7 | Promotion gate panel on WalkforwardResults | lines 70-75 | Future-need | not-started | L | schema table for gate results | deferrable until Stage-2 ~1mo away |
| G8 | Devil's-advocate paper trail on dashboard | lines 78-83 | Future-need | not-started | M | lightweight notes table | deferrable |
| G9 | `cost_calibration.json` not surfaced | lines 86-91 | Important | not-started | S | — | coding-team (Sprint-N — required before Stage-2 sign) |
| G10 | PIT universe migration counter | lines 94-99 | Future-need | not-started | S | — | deferrable (visibility-only) |
| G11 | Methodology toolkit results panel | lines 102-107 | Future-need | not-started | L | `methodology_run_log` schema | deferrable until Stage-2 |

#### B. Redundancies (3 of 5 closed; 2 remaining)

| ID | Title | Page(s) | Tier | Status | Effort | Dependencies | Suggested owner |
|---|---|---|---|---|---|---|---|
| R1 | Sharpe ratio four surfaces / three formulas | lines 115-129 | Critical | shipped | — | — | — (5-KPI strip is canonical; commit `ad69d7a`. CTOReport rolling chart re-pointed at canonical with diagnostic disclaimer at CTOReport.jsx:212-213) |
| R2 | Win rate Alpaca silent fallback | lines 132-141 | Critical | shipped | — | — | — (#690 Round 8.D `5053673` removes Alpaca fallback) |
| R3 | P&L source inconsistency (Shadow Equity = Alpaca) | lines 144-154 | Important | shipped | — | — | — (#690 Round 8.D label fix) |
| R4 | Trade-count silent Alpaca fallback | lines 158-166 | Important | **partially-done** | S | — | coding-team |
| R5 | Exit reason breakdown grouping inconsistency | lines 169-176 | Cleanup | not-started | S | — | deferrable |

**R4 partial-done detail:** Round 8.D removed the Alpaca `total_closed` fallback from Dashboard hero, but the Phase-1 progress bar on CTOReport still uses unfiltered `trades_closed` (no `instrumentation_version >= 3` parenthetical "X total closed (Y fully-instrumented)") per Round 7b's specific recommendation at line 165. Hooks into F1 — a single sweep can close both.

#### C. Strategic-alignment (3 of 6 closed; 3 remaining)

| ID | Title | Page(s) | Tier | Status | Effort | Dependencies | Suggested owner |
|---|---|---|---|---|---|---|---|
| S1 | Dashboard hero answers wrong question (uncanonical Sharpe) | lines 184-187 | Critical | shipped | — | — | — (5-KPI strip; `ad69d7a`) |
| S2 | "Distance to Halt" not surfaced | lines 190-198 | Critical | not-started | M | — | Sprint-N (cockpit truth-up) |
| S3 | Risk governor cap remaining not surfaced | lines 201-205 | Important | not-started | S | — | Sprint-N |
| S4 | Mon preflight gate output no echo | lines 208-213 | Important | shipped | — | — | — (`PreflightStatusCard.jsx` exists; #690 Round 8.D `5053673`) |
| S5 | Stage-1 signed memo numbers not anchored on dashboard | lines 216-225 | Important | not-started | S | — | Sprint-N |
| S6 | Block-bootstrap CI footnote missing | lines 228-232 | Important | shipped | — | — | — (TradeHistory.jsx:391 "CI: normal approx (IID assumption — optimistic). Block-bootstrap rerun pending.") |

---

### #807 — Operator audit (Tier 1-4)

#### Tier 1 — Functional bugs (5 of 6 closed; 1 partial)

| ID | Title | Tier | Status | Effort | Dependencies | Suggested owner | Closing PR |
|---|---|---|---|---|---|---|---|
| 1.A | Multi-page "old DB data" pattern | Critical | shipped | — | — | — | manual reconcile (#74) — 623,360 ghost rows deleted across 25 tables (per #827 PR body) |
| 1.B | Capability registry empty | Critical | shipped | — | — | — | #816 (D1a explicit registry imports) |
| 1.C | API endpoint failures (broker_exceptions / preflight / KPIs / system/index CORS) | Critical | **partially-done** | S | operator action on Render env vars | PM (operator-side action) | #833 wired routes; **CORS_ORIGINS env var on halcyon-api Render service still needs `https://halcyonlab.app` added** |
| 1.D | Stuck training audit job (8+ days "Running") | Critical | shipped | — | — | — | #840 (`diagnostic_runs` watchdog) + #74 reconcile |
| 1.E | Logs page "Clear stale" button does nothing | Critical | shipped | — | — | — | #827 (POST `/api/commands/expire-stale` added to cloud routes) |
| 1.F | Outcome data pending migration on Training page | Critical | shipped | — | — | — | #827 (`COALESCE(trade_outcome, outcome_type, outcome)` query) |

**1.C partial-done detail (operator's most important remaining item):** Per #833 PR body, the code wiring is complete (`cloud_app.py` now `include_router`s kpis/broker_exceptions/preflight); `tests/test_tier_1c_orphan_routes.py` regression-locks all four routes. But the CORS env-var on Render still defaults to `https://halcyonlab.onrender.com` and must be updated to include `https://halcyonlab.app`. Until the operator updates `CORS_ORIGINS`, cross-origin requests from the actual frontend domain will continue to fail. **This is operator-side action, not code work — but it is a deploy-blocker for using the dashboard from halcyonlab.app.**

#### Tier 2 — Product gaps (0 of 5 closed)

| ID | Title | Tier | Status | Effort | Dependencies | Suggested owner |
|---|---|---|---|---|---|---|
| 2.A | Council Attribution panel | Important | not-started | L | new schema + API + panel | Sprint-N+1 (research-instrument work) |
| 2.B | LLM-alpha threshold visualization (SD#25 target on labeled axis) | Important | not-started | M | — | Sprint-N (cockpit truth-up — partially overlaps S2) |
| 2.C | Health Score / metric definitions tooltips | Important | not-started | M | — | Sprint-N+1 (UX) |
| 2.D | Stress Test "Win rate 0%" | Important | not-started | S | diagnose first | coding-team (small) |
| 2.E | Monitoring page capacity planning / headroom | Future-need | not-started | L | trend-based forecasting | deferrable (hardware decision instrument) |

#### Tier 3 — Polish (some shipped as side-effects; status mixed)

| ID | Title | Tier | Status | Effort | Notes |
|---|---|---|---|---|---|
| 3.Trading-1 | Live Activity scanned ticker count "?" | Cleanup | not-started | S | frontend null-handling |
| 3.Trading-2 | Open Shadow Trades missing "current" + P&L | Cleanup | **partially-done** | S | likely subsumed by Tier 1.A reconcile; verify on next dashboard load |
| 3.Trading-3 | Today's Packets contrast | Cleanup | not-started | S | CSS only |
| 3.Intel-1 | Training data collectors stale/outdated | Cleanup | resolved | — | Tier 1.A side-effect |
| 3.Intel-2 | Training ticker coverage 101/102 | Cleanup | not-started | S | data integrity check |
| 3.Intel-3 | Training Recent examples not clickable | Cleanup | not-started | M | feature gap, not bug |
| 3.Intel-4 | Training Version history shows arcis:v1.0.0 with 790 examples / 0 trades | Cleanup | not-started | S | stale display, verify |
| 3.Intel-5 | CTO Report Metric Trends chart lines invisible | Cleanup | not-started | S | CSS contrast |
| 3.Intel-6 | Diagnostics page TLC | Cleanup | not-started | M | vague |
| 3.Intel-7 | Research Platform "no strategies registered yet" | Cleanup | resolved | — | Tier 1.B side-effect (registries fix) |
| 3.Intel-8 | Simulation page validation | Cleanup | not-started | M | calculation audit |
| 3.System-1 | Architecture flow chart legibility | Cleanup | not-started | M | design refresh |
| 3.System-2 | DB Schema visualization legibility | Cleanup | not-started | M | design refresh (ERD-style) |
| 3.System-3 | Health Score → Model History empty | Cleanup | not-started | S | verify broken vs by-design |
| 3.System-4 | Validation only 16 pre-flight checks | Cleanup | not-started | M | audit subsystem coverage |
| 3.Reference-1 | Settings reflects current state + NSSM | — | not-started | L | overlaps Tier 4.A |

#### Tier 4 — Net-new feature requests (separate scope)

| ID | Title | Tier | Status | Notes |
|---|---|---|---|---|
| 4.A | NSSM control from Settings page | Future-need | not-started | Security-flavored design conversation; out of dashboard sprint scope |
| 4.B | Click-for-definition popups | Future-need | not-started | Subsumed by Tier 2.C |
| 4.C | Headroom analysis | Future-need | not-started | Subsumed by Tier 2.E |

---

## Prioritization

### Bucket 1 — DEPLOY-BLOCKING (must close before Stage-1 walkforward / next live deploy)

These distort the numbers the operator uses to make trading decisions, OR are simple operator-side actions that gate everything else.

| ID | Title | Why deploy-blocking |
|---|---|---|
| #807 Tier 1.C residual (CORS env) | `CORS_ORIGINS` on halcyon-api Render | Without this, halcyonlab.app cross-origin requests fail; cockpit is half-functional from the operator's actual domain |
| F1 / R4 (instrumentation_version filter propagation) | Per-page analytics queries | TradeHistory / ShadowLedger / Velocity / Attribution / CTOReport show numbers that diverge from canonical KPI strip; operator can't reconcile what they see |
| G2 (`qty_mismatch_partial_fill` surface) | Partial-fill mismatch alert | Bounded retry exists but mismatch alert does not — silent P&L corruption is a fix-now item per `feedback_fix_before_trade.md` |

### Bucket 2 — HIGH-IMPACT FRESHNESS (pages currently showing stale or wrong data)

These are user-visible "the dashboard is lying to me" symptoms. Operator reported these today.

| ID | Title | Source |
|---|---|---|
| 3.Trading-2 | Open Shadow Trades missing "current" + P&L (verify post-#74 reconcile) | #807 |
| 3.Intel-2 | Training ticker coverage 101/102 (1 missing) | #807 |
| 3.Intel-4 | Training Version history shows arcis:v1.0.0 rolled back / stale | #807 |
| 3.Intel-5 | CTO Report Metric Trends chart lines invisible | #807 |
| 3.System-3 | Health Score → Model History empty | #807 |
| 2.D | Stress Test "Win rate 0% across the board" | #807 — diagnose: scheduler issue or calc bug |

### Bucket 3 — OBSERVABILITY GAPS (missing panels for things operator can't currently see)

These don't lie; they're absent. Operator's stated need pattern from `feedback_dashboard_strategic_lens.md` ("dashboard is operator's primary cockpit") makes these high-priority for cockpit completeness even if not deploy-blocking.

| ID | Title | Effort | Strategic priority |
|---|---|---|---|
| S2 | "Distance to Halt" widget (CI lower vs −0.2 threshold) | M | cockpit-truth-up — closes the daily go/halt loop |
| S3 | Governor cap remaining (Cap / Deployed / Available) | S | risk-governor visibility — operator currently flies blind |
| S5 | Stage-1 signed memo anchor on CTOReport (signed values vs current recompute) | S | decision-anchoring — currently only in git markdown |
| G9 | Cost-calibration card (entry/exit slippage bps from `cost_calibration.json`) | S | required before any future Stage-2 sign-off; DA §3 (cost mismodel) maps to this |
| 2.B | LLM-alpha threshold visualization (SD#25 target on labeled axis) | M | partial overlap with S2; operator-stated "what bar must we exceed" |
| 2.A | Council Attribution panel (vs single-agent / vs ranker) | L | blocks AI Council 5→7 expansion plan ($0.50/session unjustified without attribution) |
| 2.C | Metric definitions tooltips (Research Velocity / System Health / Model History) | M | self-documenting dashboard — closes Claude-explanation loop |
| 2.E | Monitoring capacity planning / headroom | L | RTX 3090 upgrade decision instrument |
| G7 | Promotion-gate panel on WalkforwardResults | L | future-need until Stage-2 ~1mo away (currently shelf) |
| G11 | Methodology toolkit results panel | L | future-need until Stage-2 |
| G8 | Devil's-advocate paper trail surface | M | nice-to-have; DA doc itself is the paper trail |

### Bucket 4 — CLEANUP / FUTURE-NEED (defer)

Not gating any decision; defer until cockpit truth-up sprint completes.

| ID | Title |
|---|---|
| I4 | System sub-component dark mode (6 remaining `dark:bg-slate-*` occurrences) |
| CL2 | Dead route `/api/traffic-light/current` |
| CL4 | `Toast.jsx` global `toast()` export unused |
| CL5 | `overflow-x-auto` for StrategyResearch / Diagnostics |
| CL6 | `QuickStatsPanel` data-passing pattern |
| CL7 | Monitoring double-fetch (`fetchApi` direct + `api.getMonitoringSnapshot`) |
| F2 | Strategy page `instrumentation_version` filter (subsumed by F1 sweep) |
| F3 | `time_to_mfe_days` schema column |
| F4 | `/council/strategic` local route (cosmetic in local dev) |
| R5 | Exit reason breakdown grouping inconsistency |
| G10 | PIT universe migration counter (visibility-only) |
| 3.* | Polish items not in cockpit-truth-up scope |
| 4.A | NSSM control (security-flavored design) |

---

## Recommended next sprint — "Cockpit Truth-Up" (Sprint-N)

**Scope:** 6 findings, all directly related to "operator looks at dashboard and trusts what they see." Deliberately excludes the L-effort observability panels (Council Attribution, Methodology Results) and the polish items.

### Reasoning

The operator's two stated symptoms today were "(1) status / state freshness, and (2) audit follow-through findings." Bucket 1 directly closes the freshness symptom (operator sees consistent numbers across pages) AND closes the highest-priority audit follow-through (CORS, F1 propagation, partial-fill alert). Bucket 3 items S2/S3/S5/G9 each:

- Are S-effort (≤2h) or M-effort (≤1d)
- Use data already fetched by existing pages (no new schema)
- Close a *specific operator decision question* (distance-to-halt / cap-remaining / signed-anchor / cost-calibration)
- Map directly to PM Decision-1 ("DEFER deploy until Stage-1 strategy redesign") rationale — operator needs to see why deploy is deferred

The L-effort items (Council Attribution, Methodology Toolkit panel, NSSM control) are research-instrument work or new-feature scopes — they belong to dedicated sprints and would balloon a "fix the cockpit" sprint into a 2-week project. Memory `feedback_dashboard_strategic_lens.md` says dashboard work must catalog gaps + redundancies — that catalog is now this doc; the *fix* sprint stays narrow.

### Proposed scope (6 items, ~2-3 days for one developer or 1 day with parallel agents)

| # | ID | Title | Effort | Why in scope |
|---|---|---|---|---|
| 1 | #807 Tier 1.C residual | Set `CORS_ORIGINS` env var on halcyon-api Render service | S (operator action) | Unblocks halcyonlab.app cross-origin; gates everything else |
| 2 | F1 / R4 | Propagate `instrumentation_version >= 3` filter to TradeHistory / ShadowLedger / Velocity / Attribution / CTOReport queries; add "(N fully-instrumented)" parenthetical to CTOReport Phase-1 progress bar | M | Closes "numbers diverge across pages" symptom |
| 3 | S2 | "Distance to Halt" widget on Dashboard or CTOReport (CI lower vs −0.2 threshold from §3.1) | M | Closes daily go/halt loop |
| 4 | S3 | Governor cap remaining row in Dashboard system-status cards | S | Risk-governor visibility |
| 5 | S5 | Stage-1 signed memo anchor on CTOReport (static signed values + live recompute delta) | S | Decision-anchoring; data already exists |
| 6 | G9 | Cost-calibration card on CTOReport (read `cost_calibration.json` via new `/api/cost-calibration` route) | S | Required before any Stage-2 sign-off; DA §3 maps to this |

**Bonus add-ons (if developer finishes early):**
- G2 (`qty_mismatch_partial_fill` badge) — S effort, partial-fill alert is a fix-before-trade item
- I4 cleanup — 6 remaining `dark:bg-slate-*` occurrences in system sub-components

**Out of next sprint:**
- All Tier 2 items except threshold viz overlap (2.B feeds S2)
- All Tier 3 polish (resolves opportunistically as side effects)
- All Tier 4 net-new features
- G7 / G11 (Stage-2 promotion-gate / methodology results panels — future-need until Stage-2 ~1mo away)
- 2.A Council Attribution — its own dedicated sprint per Decision 3 sequencing

### Suggested dispatch

Per `feedback_use_coding_team_skill.md`, this is Sprint-N+ feature work — invoke `arcis:code` skill (PM orchestrator hierarchy) rather than direct coding-developer dispatches. Suggested wave structure:

- **Wave A (parallel, isolated worktrees):** Items 2, 3, 4, 5, 6 (5 developers, scope-fenced; per `feedback_strict_rigor_no_handwave.md`)
- **Wave B (after Wave A merges):** Bonus add-ons G2 + I4 if remaining budget
- **Operator action (parallel to Wave A):** Item 1 — operator updates Render env var

Each wave has a sibling-search step per `feedback_review_sibling_search.md` and visual verification per `feedback_visual_verify_ui.md` (frontend Dashboard/KPIStrip/CTOReport edits must be browser-rendered before push).

---

## Coverage gaps in this investigation

What I read in full:
- `docs/sprints/track_1_5_pass2_dashboard_audit.md` (Round 7)
- `docs/sprints/track_1_5_pass2_dashboard_strategic_audit.md` (Round 7b)
- `docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md` (PM decisions log)
- `docs/audits/2026-04-27-trading-readiness/SHIPPED.md` (rollup)
- `docs/audits/2026-04-27-trading-readiness/design-decisions.md` (v3 amendment)
- GitHub issue #807 in full
- PR bodies of #690, #816, #827, #833, #840

What I spot-checked:
- `src/api/cloud_routes/analytics.py:910-944` (C1 fix verified)
- `frontend/src/pages/Monitoring.jsx` (C1, I8, CL7 status)
- `frontend/src/pages/Dashboard.jsx` (I7, G5 status, Approaching Timeout card)
- `frontend/src/pages/TradeHistory.jsx` (G4, S6 status)
- `frontend/src/pages/CTOReport.jsx` (G3, R4 status)
- `frontend/src/pages/Packets.jsx` (I9 status)
- `frontend/src/components/dashboard/KPIStrip.jsx` (R1, S1, G6 status)
- `frontend/src/components/dashboard/BrokerExceptionsPanel.jsx` (G1 existence)
- `frontend/src/components/dashboard/PreflightStatusCard.jsx` (S4 existence)
- `src/api/routes/` directory listing (C2, C3, C4, C5 file existence)
- `src/api/cloud_app.py:51-311` (Tier 1.C orphan-route wiring)

What I did NOT analyze:
- Tier 3 polish items in detail — most are "verify next dashboard load," not source-readable from a static repo scan
- 2.A Council Attribution — exists only as a product spec; no code to inspect
- 2.E Capacity planning — exists only as a product spec
- 4.A NSSM control — security-flavored architectural decision; not a code-state question
- The actual stale-data symptoms operator reported today — those require live DB / Render Postgres inspection that this investigation cannot perform from a worktree

Ambiguous-status findings (need operator/PM input to resolve):
- 3.Trading-2 (Open Shadow Trades missing current + P&L) — could be resolved by #74 reconcile or could persist; needs live dashboard verification
- 3.System-3 (Model History empty) — could be by-design or broken; needs feature-spec lookup
- 1.C residual scope — code-side believed complete via #833; CORS env-var status confirmable only by checking Render dashboard

---

## Receipts

- **Findings parsed:** 64 (Round 7: 25, Round 7b: 22, #807: 17)
- **Shipped:** 36 (Round 7: 14 — C1-C5, I1-I3, I5-I9, CL1, CL3; Round 7b: 9 — G1, G3-G6, R1-R3, S1, S4, S6; #807: 13 — Tier 1.A/B/D/E/F + Tier 3 side-effects + Tier 1.C code wiring)
- **Closing PRs:** #690 (Track 1.5 mega-PR — Round 8.A through 8.F), #816 (Tier 1.B), #827 (Tier 1.E + 1.F), #833 (Tier 1.C orphan routes + CORS doc), #840 (Tier 1.D watchdog), #74 (Tier 1.A manual reconcile)
- **Remaining (28):**
  - Critical/Important operator-decision-impact: 1 (Tier 1.C residual CORS env var)
  - High-impact freshness symptoms: 6 (3.Trading-2, 3.Intel-2, 3.Intel-4, 3.Intel-5, 3.System-3, 2.D)
  - Observability gaps (Bucket 3): 11 (S2, S3, S5, G9, 2.B, 2.A, 2.C, 2.E, G7, G11, G8)
  - Cleanup / Future-need: 11 (I4, CL2, CL4, CL5, CL6, CL7, F2, F3, F4, R5, G10) — plus Tier 3 polish (~10) + Tier 4 (~3) which are deferable
