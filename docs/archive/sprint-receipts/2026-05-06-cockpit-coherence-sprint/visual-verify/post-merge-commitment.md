# Sprint 3 Post-Merge Commitment — Hard Verification Rubric

**Created**: 2026-05-07
**Purpose**: Per-finding commitment table mapping each audit finding (`docs/audits/2026-05-06-dashboard-coherence/summary.md` + `cross-cutting.md`) to the exact post-merge state Sprint 3 commits to delivering. This is the visual-verify gate the operator declared a hard requirement.

**Three commitment classes:**
- **CLOSE**: Sprint 3 task ships a fix; post-merge state must match the "Expected" column. Failure = sprint not done.
- **DEFER**: Out of Sprint 3 scope per spec (Group D/G/H/I or T4 E2 downgrade). Tracked as Sprint 4 follow-up; "before" state acceptable to remain.
- **DATA**: Not a UI bug — a data-pipeline state. Sprint 3 makes the state legible (e.g. cohort badge) but doesn't change underlying numbers.

## CRITICAL findings (audit summary.md)

| ID | Audit before | Class | Sprint 3 task | Expected post-merge state | Verification |
|----|-------------|-------|---------------|---------------------------|--------------|
| 01-C1 | Header `25 POSITIONS` ≠ body `OPEN TRADES: 0` | CLOSE | T10 | Header POSITIONS reads `/api/status._meta.open_positions.n`. Tooltip on the count shows `_meta.open_positions.label`. Number reconciles with `/api/live/summary.open_positions`. | Header text matches body Open Trades count; tooltip text present |
| 01-C2 | WIN RATE 80.0% (KPI) vs 12.0% (Account) no cohort label | CLOSE | T5+T8+T12 | Each KPI card has `data-testid="kpi-meta-badge"` rendering `n=N · <last-cohort-segment>` italic muted text below value. KPI strip reads `kpis._meta.win_rate.cohort='kpi.canonical'`; Account block label `kpis._meta.<field>.cohort='trades.all_closed'`. | DOM check: badge present under each Win Rate value; cohort_id strings differ |
| 01-C3 | Header `TL: NOT SET` | CLOSE | T10 | Header reads `kpis.stage_traffic_light.decision_matrix_state` via shared `['kpis']` queryKey. Four states: `TL: GREEN/AMBER/RED` (colored) / `TL: …` (isPending) / `TL: COMPUTING` (decision_matrix_state==null, last_computed_at tooltip if present) / `TL: ERR` (isError, last_attempt tooltip). | DOM check: text matches one of the four states; **never** `TL: NOT SET` |
| 03-C1 | Shadow Ledger `?desk=[object Object]` in network requests | CLOSE | T21 | All `useQuery({queryFn: api.X})` bare-ref sites in ShadowLedger.jsx (lines 476, 478, 481) wrapped as arrow form `() => api.foo(arg)`. Network panel shows `?desk=swing` (or `desk=live` etc.), never `?desk=%5Bobject+Object%5D`. ESLint rule (T22) blocks regression. | Network filter for `[object` returns zero hits while interacting with desk filter |
| 03-C2 | WIN RATE 12% + PROFIT FACTOR 6.21 + MAX DD 0.1% statistically incompatible | DATA | (cohort labels via T8/T9) | Numbers unchanged; cohort label disambiguates which sample (all closed vs canonical). Acceptable for the numbers to remain "weird" if cohort makes intent clear. | Cohort badge present clarifies the sample |
| 05-C1 | Trade History `stop loss` POSITIVE +$82.08 vs Model Perf NEGATIVE | DEFER | T4 (E2 downgraded) | Backend math verified correct in `executor.py` + `reconcile.py` per T4 investigation. Sign-flip is in some downstream display layer not yet identified. **Sprint 4 follow-up `#SP4-stop-loss-fallback`**. | NOT verified post-merge — Sprint 4 deliverable |
| 05-C2 | 88% of exits via `reconciled_stale` (44/50) | DATA | (operational signal — out of dashboard sprint scope) | NOT closed; cohort badges + reconciliation test surface the data, but the operational issue itself isn't a UI bug. | NOT verified |
| 05-C3 | Trade History `?desk=[object Object]` URLs | CLOSE | T19 | TradeHistory.jsx:238 (`getSharpeAttribution`) wrapped in arrow form. Network panel shows valid filter strings. | Same as 03-C1: network filter for `[object` returns zero |
| 06-C1 | Strategy 4th cohort 83.3% N=6 unlabeled | CLOSE | T9+T12 | Strategy page renders `data-testid="strategy-meta-badge"` from `/api/strategy-detail._meta` with `cohort='trades.strategy'`. | DOM check: badge present under per-strategy stats |
| 07-C1 | `training_corpus = 42` here vs 13,560 LLM corpus elsewhere | DATA | (label disambiguation only) | Numbers unchanged; cohort labels via cohort_meta.py make scope explicit. | Acceptable as-is per spec |
| 07-C2 | TOTAL EXAMPLES 42 but OUTCOME DISTRIBUTION 0/0/0/0 | DATA | (data-pipeline state) | NOT closed — separate from cockpit coherence sprint. | NOT verified |
| 08-C1 | Council "307 open positions / 20 closed trades" stale | DATA | (Council page redesign deferred per recommendations.md) | NOT closed | NOT verified |
| 08-C2 | Council "0% fallback rate" reasoning over packet_writer bug | DATA | (out of scope; tracked as separate task #52) | NOT closed | NOT verified |
| 08-C3 | Council `Ask Council` button always disabled (form trap) | CLOSE | T14 | Ask Council button uses ActionButton with `cliOnly=false` + onClick mutation preserved. Disabled only when input empty (pending=isPending OR !question.trim()). | Click works when input non-empty |
| 09-C1 | CTO Report `TRADES OPEN: 25` (origin of header divergence) | CLOSE | T8+T10 | Header no longer sources from `/api/cto-report` — sources from `/api/status._meta.open_positions` (T10). CTO endpoint emits `_meta` envelope but its number stays as-is for the report; the divergence is closed at the consumer side. | Header POSITIONS == /api/status, not /api/cto-report |
| 09-C2 | TOTAL P&L $362.49 here vs $427.35 Trade History | CLOSE | T16 | T16's `test_closed_count_reconciles` asserts cohort match BEFORE n equality. If cohorts match between endpoints, n must reconcile (CI test). If cohorts differ, divergence is "by design" (cohort label makes it legible). | CI green at integration merge; both endpoints emit _meta with cohort label |
| 09-C3 | Phase 1 Gate Progress = 6/50 (5 fully-instrumented) | DATA | (sixth Phase-1 definition is spec drift, out of scope) | NOT closed — definition disambiguation is a separate concern | NOT verified |
| 10-C1 | Attribution `INSUFFICIENT (841/200)` contradicts subtitle `sufficient` | CLOSE | T2 | Attribution badge label reads `(${paired_n}/200)` where `paired_n = COUNT(*) FROM attribution_trades WHERE ranker_only_outcome != 'pending' AND llm_portfolio_outcome IS NOT NULL`. Subtitle says `X paired trades resolved (both arms)`. **Math no longer inverted**: if paired_n < 200 → INSUFFICIENT badge AND subtitle agrees. Currently expect paired_n very small (since "0 resolved" before). | Badge `paired_n` matches subtitle count; both consistent |
| 10-C2 | 770 pairs but 0 resolved (outcome-resolution gap) | DATA | (mirrors Training C2 — data-pipeline state) | NOT closed; T2 reformulates the gate but doesn't fix the data | NOT verified |
| 11-C1 | Active model `0 training examples` and `Created —` | DATA | (model metadata empty in DB) | NOT closed | NOT verified |
| 11-C2 | PROFIT FACTOR 999 sentinel (Model Perf) | CLOSE | T4+T14 | Backend `engine.py:458` emits Python `None` for inf case (not 999.0). Frontend Simulation.jsx + StressTest.jsx render `null` as `'N/A (no losses)'`. ModelPerformance page shows numeric values when finite. **Never literal 999**. | DOM check: scan all numeric "PROFIT FACTOR" cells; 999 not present |
| 11-C3 | stop_loss +$82.08 vs -$82.08 cross-page | DEFER | T4 (E2 downgraded) | Backend correct per T4 investigation; downstream display flip is **Sprint 4 `#SP4-stop-loss-fallback`**. Acceptable for current state to remain visible. | NOT verified post-merge |
| 12-C1 | Velocity heading `(falls back to duration until time_to_mfe_days column lands)` | DEFER | (out of Sprint 3 scope — schema work) | NOT closed | NOT verified |
| 14-C1 | Research Platform "No strategies registered" but Strategy page shows Pullback | DATA | (parallel registries — out of scope) | NOT closed | NOT verified |
| 15-C1 | Stress Test all 7 scenarios show 0.0% WR | DEFER | Group I (operator-honest banner deferred) | NOT closed; expected behavior per spec — but operator-honest banner explaining "by design" deferred to Sprint 4. | NOT verified post-merge |
| 18-C1 | DB Schema subtitle `loading tables across 6 domains` placeholder | CLOSE | T13 | DBSchema.jsx wraps in `<LoadingState>`. While loading shows spinner; on error shows error card with retry; on data shows ReactFlow graph. **No literal "loading..." placeholder string visible to operator after data loads.** | DOM check: subtitle reflects loaded data, not literal "loading tables across 6 domains" |
| 18-C2 | `/api/system/table-counts` pending forever | CLOSE | T13 | useQuery destructures isError; LoadingState surfaces error with retry button if API hangs/errors. | Network shows resolved request OR error card visible (not infinite spinner) |
| 21-C1 | `/api/monitoring/history` 503 × 3 | CLOSE | T3 | Backend wraps query in try/except. On UndefinedTable or any Exception, returns HTTP 200 with `{snapshots: [], note: 'system_metrics is local-only; view at http://localhost:8000/api/monitoring/history'}`. | Network: GET /api/monitoring/history returns 200, not 503 |
| 21-C2 | Page completely unusable; renders only `LOADING...` | CLOSE | T3+T13 | T13 wires `isError` from useQuery to LoadingState. Even if server 5xxs, frontend shows error card with retry, never infinite spinner. | DOM: page renders content (cloud-mode banner / metrics / error card), never stuck loading |
| 23-C1 | Settings `value="0.004999999888241291"` (float-precision) | CLOSE | T11 | SettingInput two-layer clamp: (a) mount uses `parseFloat(value.toFixed(decimalsFromStep(step)))` so initial render shows `0.005`; (b) onBlur emits clamped value when `Math.abs(localValue - displayValue) < step/2`. | DOM check: spinbutton `value` attribute === `0.005` (not `0.004999999888241291`); same for Risk % Max |
| 24-C1 | Roadmap "Updated 2026-04-26" 10-day stale | DEFER | Group D (hardcoded content deferred to Wave 4) | NOT closed | NOT verified |
| 24-C2 | Roadmap Calmar 8299.71 | CLOSE | T1 | `analytics.py:568` replaced with canonical `calmar_ratio()` from `src/evaluation/statistics.py`. Formula: `ann_ret / max_dd_pct`. With current data (~8% ann_ret, 11.9% max_dd) expect Calmar **~0.5-1.5 range**, not 1141 or 8299. CI guardrail (T1-followup, T22) prevents new ad-hoc Calmar formulas. | DOM check: Calmar value reads in 0.5-1.5 range |

## Cross-cutting patterns (cross-cutting.md)

| Pattern | Class | Tasks closing it | Verification |
|---------|-------|------------------|--------------|
| 1. Cohort proliferation without labeling | CLOSE | T5+T8+T9+T12 | Every KPI cell flagged in audit shows a cohort badge with `n=N · <segment>` |
| 2. Header source-of-truth divergence | CLOSE | T10 | Header sources from `/api/kpis` + `/api/status` (no longer `/api/cto-report`) |
| 3. Stuck LOADING state | CLOSE | T3+T6+T13 | Monitoring/DBSchema/Health/BrokerExceptions render error card or empty state, never infinite spinner |
| 4. Hardcoded React content | DEFER | (Group D — Wave 4) | NOT verified |
| 5. Stale request leaks (`pending` forever) | PARTIAL | T17-T22 (arrow form) — fixes the bare-ref class; explicit timeout/cancel not addressed | Network panel — useQuery requests resolve to data/error/empty |
| 6. Float-precision in inputs | CLOSE | T11 | Settings inputs render clean step-precision values |
| 7. `desk=[object Object]` URL bug | CLOSE | T17+T20+T21 + T22 ESLint | Network filter for `[object` returns zero |
| 8. Sentinel/overflow values displayed | PARTIAL | T1 (Calmar), T4 (profit_factor) | No 999 or 8299 anywhere; Sharpe small-sample disclaimer NOT added |
| 9. Empty-success rendered as failure | DEFER | (Group I — Wave 4) | NOT closed (`shadow_trade_cohort: unavailable` still rendered) |
| 10. Operational signals not aggregated | DEFER | (Group H — system-narrative panel deferred) | NOT closed |
| 11. Operator-action ambiguity | CLOSE | T7+T14+T15 | LiveLedger Reconcile, Settings IB, Council Run/Ask, Diagnostics, Simulation Run all have ActionButton or whyDisabled tooltip |
| 12. Non-deterministic chart auto-tick gaps | DEFER | (NIT — Wave 4) | NOT closed |
| 13. Cross-page label inconsistency | DEFER | (Group G — style guide deferred) | NOT closed |

## Summary of commitment scope

- **CLOSE (Sprint 3 owns)**: 18 findings — must verify post-merge or sprint NOT done.
- **DEFER (Sprint 4 owns)**: 7 findings — must NOT regress, but won't be "closed" by Sprint 3 deploy. Tracked as `#SP4-*` issues.
- **DATA (state, not bug)**: 8 findings — Sprint 3 makes them legible via cohort badges but doesn't change underlying numbers.

**Visual verify procedure post-integration-merge to main:**
1. Wait for Render redeploy (~5-10 min).
2. Re-capture all 11 priority pages → `visual-verify/after/`.
3. Walk each CLOSE-class row above; confirm "Expected" matches reality.
4. Document PASS/FAIL/N-A per row in `visual-verify/results.md`.
5. If any CLOSE row FAILs → dispatch hot-fix agent BEFORE marking Sprint 3 complete.
6. DEFER + DATA rows logged as expected-not-closed; surface to operator as known carry-overs.
