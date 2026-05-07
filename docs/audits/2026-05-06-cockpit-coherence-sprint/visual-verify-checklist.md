# Sprint 3 Cockpit Coherence — Operator Visual-Verify Checklist

**Purpose**: Post-integration-merge-to-main validation checklist for halcyonlab.app.
**Run after**: Render rebuild completes following the Sprint 3 base → main merge.
**Operator**: Execute each item at https://halcyonlab.app in a logged-in browser session.

---

## Pre-flight

- [ ] Render deployment shows "Deploy successful" (check Render dashboard)
- [ ] `git ls-remote origin main` SHA matches expected merged commit
- [ ] Hard-refresh browser (Cmd/Ctrl+Shift+R) to bust Vite bundle cache
- [ ] Open browser DevTools → Console — confirm no unhandled JS errors on initial load

---

## Group E — Correctness Bug Fixes

### E5: Calmar 1000x overshoot (T1, PR #987)

| | |
|---|---|
| **Page** | Health → CTO Report or any page showing `calmar_ratio` |
| **Pre-merge state** | `calmar_ratio` was inflated ~1000x due to `ann_ret / (max_dd / 100000 * 100)` |
| **Expected post-merge** | `calmar_ratio` is a plausible value (typically 0.1–5.0 for a real strategy; not thousands) |
| **Test** | Navigate to a page that shows `fund_metrics.calmar_ratio`. Confirm value is in range 0–10. |

- [ ] PASS — calmar_ratio shows reasonable value
- [ ] FAIL — value is anomalously large (>100)

### E6: Attribution paired-overlap gate (T2, PR #988)

| | |
|---|---|
| **Page** | Attribution |
| **Pre-merge state** | Gate used marginal counts (`rr` or `lr`), not paired-overlap count |
| **Expected post-merge** | Label shows `(N/200)` where N is the count of trades resolved in BOTH arms |

- [ ] PASS — Attribution page shows `(X paired trades resolved (both arms))` label
- [ ] FAIL — label text is old format or N is unexpectedly large

### E7: Monitoring 500/503 fix (T3, PR #990)

| | |
|---|---|
| **Page** | Monitoring |
| **Pre-merge state** | `/api/monitoring/history` raised 500 on Render (system_metrics is local-only); Monitoring page showed infinite spinner |
| **Expected post-merge** | Monitoring page shows either: (a) real data if system_metrics is present, or (b) an empty-state message with note "system_metrics is local-only" |

- [ ] PASS — Monitoring page loads without spinner hang; shows data or informative empty state
- [ ] FAIL — page still shows infinite spinner or error card

### E2: stop_loss sign (T4, PR #988)

| | |
|---|---|
| **Page** | Live Ledger or Trade History (closed trades with exit_reason='stop_loss') |
| **Pre-merge state** | stop_loss trades may show incorrect P&L sign |
| **Expected post-merge** | stop_loss trades show negative P&L (this is a backend fix; display sign-inversion is tracked as #SP4-stop-loss-fallback) |

- [ ] PASS — stop_loss exits show negative P&L values in trade lists
- [ ] FAIL — stop_loss exits show positive P&L (display sign-inversion not yet fixed — file as #SP4-stop-loss-fallback if not already)

### E4: profit_factor None sentinel (T4, PR #988)

| | |
|---|---|
| **Page** | Simulation or Stress Test |
| **Pre-merge state** | profit_factor showed `999.0` when there were no losses |
| **Expected post-merge** | profit_factor shows `N/A (no losses)` when no losing trades in scenario |

- [ ] PASS — scenarios with no losses show "N/A (no losses)" for profit_factor
- [ ] FAIL — shows `999` or empty

---

## Group A — Cohort Taxonomy

### A3: KPICard cohort badge (T5, PR #986)

| | |
|---|---|
| **Page** | Dashboard (KPIStrip) |
| **Pre-merge state** | KPI cards showed numeric values only, no cohort context |
| **Expected post-merge** | rf-adjusted excess Sharpe card and Win Rate card each show a small cohort badge (e.g., `n=35 · canonical`) under the headline value |

- [ ] PASS — cohort badges visible under rf-Adj and Win Rate cards
- [ ] FAIL — no badges visible

### A1.A: Backend `_meta` envelope — KPIs/CTO/Status (T8, PR #991)

| | |
|---|---|
| **API check** | Open DevTools Network tab → reload Dashboard → inspect `/api/kpis` response |
| **Expected** | Response JSON includes `_meta.rf_adjusted_excess_sharpe: { cohort: "kpi.canonical", label: "canonical", n: <int> }` |

- [ ] PASS — `_meta` envelope present in `/api/kpis`
- [ ] FAIL — no `_meta` key in response

### A1.B: Backend `_meta` on 7 additional endpoints (T9, PR #993)

| | |
|---|---|
| **API check** | Inspect `/api/shadow/metrics`, `/api/attribution/stats`, `/api/strategy-detail/*` in DevTools |
| **Expected** | Each response includes `_meta` sibling field |

- [ ] PASS — `_meta` present on all checked endpoints
- [ ] FAIL — missing on one or more endpoints

### A4: Dashboard/TradeHistory/Strategy meta consumption (T12, PR #997)

| | |
|---|---|
| **Page** | Trade History (Excess Sharpe panel), Strategy Detail page |
| **Expected** | Cohort badge visible below Excess Sharpe value; Strategy page shows meta badge when strategy has trades |

- [ ] PASS — cohort badges visible in Trade History and Strategy pages
- [ ] FAIL — badges missing

---

## Group B — Header Source-of-Truth

### B1+B2: Header TL indicator (T10, PR #992)

| | |
|---|---|
| **Page** | All pages (header bar) |
| **Pre-merge state** | Header showed `TL: NOT SET` (hardcoded in Layout.jsx) |
| **Expected post-merge** | Header shows `TL: GREEN`, `TL: AMBER`, or `TL: RED` sourced from `/api/kpis.stage_traffic_light`; shows `TL: …` (ellipsis) while loading; shows `TL: COMPUTING` if loaded but null; shows `TL: ERR` if API fails |

- [ ] PASS — header shows a real traffic light value (not "NOT SET")
- [ ] FAIL — still shows "NOT SET" or static value

### B3: CI dashboard reconciliation test (T16, PR #999)

This is a CI test, not a visual check. Confirm the test passes in CI on the merged PR.

- [ ] PASS — `tests/test_dashboard_reconciliation.py` passes in CI (check GitHub Actions)
- [ ] N/A — CI not yet configured for this suite

---

## Group C — Loading State

### C1: Shared LoadingState component (T6, PR #983)

| | |
|---|---|
| **Component** | `frontend/src/components/LoadingState.jsx` |
| **Visual check** | Navigate to Broker Exceptions panel, DB Schema, Health, Monitoring widgets; all should show spinner while loading and explicit retry button on error |

- [ ] PASS — loading states show spinner (not blank); error states show retry button
- [ ] FAIL — blank or infinite spinner on error

### C2: 4 widgets migrated to LoadingState (T13, PR #996)

| | |
|---|---|
| **Pages** | Health, Monitoring, DB Schema, any page with BrokerExceptionsPanel |
| **Pre-merge state** | These widgets had ad-hoc loading patterns (infinite spinner on error) |
| **Expected post-merge** | Error states show explicit error card with retry button |

To test error state: temporarily disconnect from network or use DevTools to block the API endpoint.

- [ ] PASS — error states show explicit retry card, not infinite spinner
- [ ] FAIL — still shows infinite spinner on API error

---

## Group F — Operator-Action Ambiguity

### F1: Shared ActionButton (T7, PR #984)

| | |
|---|---|
| **Pages** | Live Ledger (Reconcile button), Settings (IB toggles) |
| **Expected** | `[CLI only]` badge visible on buttons that require local broker auth; tooltip shows CLI command |

- [ ] PASS — `[CLI only]` badge visible on Live Ledger reconcile button
- [ ] FAIL — badge missing or button is not disabled

### F2: 4 pages migrated to ActionButton (T14, PR #998)

| | |
|---|---|
| **Pages** | Live Ledger, Diagnostic Kickoff, Simulation, Council |
| **Expected** | Buttons use ActionButton component; CLI-only buttons are visually disabled with badge; interactive buttons function normally |

- [ ] PASS — Live Ledger reconcile shows `[CLI only]` badge; Council "Run Now" button is interactive
- [ ] FAIL — buttons missing badge or non-functional

### F2.B: Settings IB toggles visually disabled (T15, PR #995)

| | |
|---|---|
| **Page** | Settings |
| **Expected** | `live_trading.ib.shadow_mode` and `live_trading.ib.paper_routing` toggles are visually grayed out with "Effect requires local IB Gateway connection" reason text |

- [ ] PASS — IB toggles are grayed out with reason text visible (no hover required)
- [ ] FAIL — IB toggles appear interactive or reason text is missing

---

## TanStack v5 Sweep (T17–T21)

### E1: No `desk=[object Object]` URL corruption

| | |
|---|---|
| **Page** | Shadow Ledger, Trade History |
| **Pre-merge state** | `ShadowLedger.jsx` bare queryFn refs caused `?desk=%5Bobject+Object%5D` in API URLs |
| **Expected post-merge** | All API requests use correct `desk` parameter values (`swing`, `live`, `all`, etc.) |

Open DevTools Network tab → navigate to Shadow Ledger → check XHR requests to `/api/shadow/trades` etc.

- [ ] PASS — no `%5Bobject+Object%5D` or `[object Object]` in any API URL
- [ ] FAIL — URL corruption still present

### E1.C: ESLint queryFn guardrail (T22, PR #1004)

This is a CI check, not a visual check.

- [ ] PASS — `npm --prefix frontend run lint:queryfn` exits 0 (all bare refs wrapped)
- [ ] N/A — not running locally

---

## Settings Risk Input Float Precision (T11, PR #985)

| | |
|---|---|
| **Page** | Settings |
| **Pre-merge state** | Float inputs showed precision artifacts (e.g., `0.0049999...` instead of `0.005`) |
| **Expected post-merge** | Float inputs clamp and display to configured precision (e.g., `0.005`) |

- [ ] PASS — Settings float inputs show clean decimal values (no trailing `9999...`)
- [ ] FAIL — float artifacts still visible

---

## Post-Checklist Sign-Off

| Item | Status |
|---|---|
| All Group E correctness bugs verified | [ ] PASS / [ ] FAIL |
| All Group A cohort badges visible | [ ] PASS / [ ] FAIL |
| Header TL indicator live | [ ] PASS / [ ] FAIL |
| All Group C loading states functional | [ ] PASS / [ ] FAIL |
| All Group F ActionButton migrations functional | [ ] PASS / [ ] FAIL |
| No `[object Object]` URL corruption | [ ] PASS / [ ] FAIL |
| Sprint 4 follow-up issues created in GitHub | [ ] DONE / [ ] PENDING |

**Operator signature**: ___________________  **Date**: ___________________
