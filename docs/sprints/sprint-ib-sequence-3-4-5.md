# IB Integration: Complete Sprint Sequence (3 of 5 remaining)

**Date:** April 11, 2026
**Author:** Claude (Opus 4.6)
**Context:** Sprints IB-1 (tests + shadow) and IB-2 (dashboard) are written. This document covers IB-3, IB-4, IB-5, plus deep research needs and the updated TODO queue.

---

# SPRINT IB-3: Dual-Execution Routing

**Depends on:** IB-1 merged + 1-2 weeks of shadow data confirming Gateway stability
**Priority:** HIGH
**Estimated CC time:** 6-8 hours

## Design Spec

### Problem

Currently every paper trade goes to Alpaca and every live trade routes through the broker factory. There's no mechanism to split paper trades across two brokers based on quality, and no cross-broker position tracking.

### Architecture

```
Executor: open_shadow_trade() receives a qualified candidate
    │
    ├── Score ≥ IB_THRESHOLD (config, default 80)
    │   ├── IB Gateway connected? ─── YES → IB paper trade
    │   │                         └── NO  → Alpaca paper (fallback)
    │   └── Record broker="ib" on shadow_trades
    │
    └── Score < IB_THRESHOLD
        ├── Alpaca paper trade (normal path)
        └── Record broker="alpaca" on shadow_trades
```

### Schema Change

Add `broker` column to `shadow_trades`:

```python
ColumnDef("broker", "TEXT", default="'alpaca'",
          description="Which broker executed: alpaca or ib. Defaults to alpaca for backward compatibility."),
```

All existing rows default to `'alpaca'`. New IB-routed trades get `broker='ib'`.

### Config

```yaml
live_trading:
  ib:
    shadow_mode: false        # Disable shadow-only (graduating to real routing)
    paper_routing: true       # Enable score-based routing for paper trades
    paper_routing_threshold: 80  # Score >= this goes to IB paper
    port: 4002                # Paper port
```

### Components to Modify

**1. Trade Router** — New function in executor:

```python
def _select_paper_broker(score: float, config: dict) -> tuple[str, BrokerAdapter | None]:
    """Select broker for paper trade based on score and IB availability.

    Returns: ("alpaca" | "ib", broker_instance_or_None)
    """
```

**2. `open_shadow_trade()`** — After computing score, call router. If IB selected:
- Use IBBroker.place_bracket_order() instead of Alpaca adapter
- Set `trade_data["broker"] = "ib"`
- IB failure falls back to Alpaca (with `broker="alpaca"`)

**3. Reconciler** — `reconcile_paper_trades()` must split by broker:
- Alpaca-brokered paper trades → reconcile against Alpaca positions
- IB-brokered paper trades → reconcile against IB positions
- Currently reconciler gets positions from ONE source — needs both

```python
# In reconcile_paper_trades:
alpaca_positions = get_all_positions()  # existing Alpaca paper
ib_positions = []
try:
    from src.trading.broker_factory import get_live_broker
    ib_broker = IBBroker(port=config.ib.port)
    if ib_broker.is_connected():
        ib_positions = ib_broker.get_all_positions()
except Exception:
    pass  # IB down — skip IB reconciliation

# Match each tracked trade to its broker's positions
for trade in tracked_paper_trades:
    if trade["broker"] == "ib":
        positions = {p.ticker: p for p in ib_positions}
    else:
        positions = alpaca_tickers
```

**4. Risk Governor** — Position counting across brokers:

```python
# In check_max_positions:
alpaca_open = count_open_by_broker("alpaca")
ib_open = count_open_by_broker("ib")
total_open = alpaca_open + ib_open
# Compare total against max_open_positions
```

**5. Bracket Monitor** — `check_bracket_health()` must check both brokers.

### Tests (12 new)

| Test | What |
|------|------|
| `test_route_high_score_to_ib` | Score 85 → IB when connected |
| `test_route_low_score_to_alpaca` | Score 72 → Alpaca |
| `test_ib_down_falls_back_to_alpaca` | IB disconnected → Alpaca, logged |
| `test_broker_column_set_on_trade` | shadow_trades.broker = "ib" for IB trades |
| `test_broker_column_default_alpaca` | Existing trades default to "alpaca" |
| `test_reconcile_separates_by_broker` | IB trades check IB, Alpaca trades check Alpaca |
| `test_risk_governor_counts_both` | 3 IB + 4 Alpaca = 7 total positions |
| `test_routing_disabled_when_not_configured` | No config → all Alpaca |
| `test_threshold_configurable` | Custom threshold from config |
| `test_bracket_monitor_checks_both` | Bracket health covers both brokers |
| `test_fallback_logs_warning` | IB failure fallback produces warning log |
| `test_live_trades_unaffected` | Live trade routing unchanged |

### Ralph Loop Findings

**Pass 1:** The `broker` column must default to `'alpaca'` (with quotes for SQLite TEXT default), not `alpaca` — existing rows need the default value without a migration script.

**Pass 2:** The reconciler currently has separate functions `reconcile_paper_trades()` and `reconcile_live_trades()`. For dual-execution, the paper reconciler needs the IB broker instance — but it shouldn't import IBBroker directly. Use the broker factory with a separate config that always returns the IB paper broker.

**Pass 3:** The fallback from IB to Alpaca must log which ticker failed and why, so we can track IB reliability over time. Add a column `ib_fallback_reason` to shadow_trades or log to `ib_shadow_log`.

---

# SPRINT IB-4: Production Hardening

**Depends on:** IB-3 merged + 2 weeks of dual-execution data
**Priority:** HIGH
**Estimated CC time:** 8-10 hours

## Design Spec

### Problem

The IBBroker adapter handles the happy path but doesn't handle 11 production edge cases documented in the gap analysis. Before activating IB paper trading at scale, these must be addressed.

### Gap Coverage

| # | Gap | Fix | Risk if Unfixed |
|---|-----|-----|----------------|
| 1 | **Gateway daily reset (11:45 PM ET)** | Auto-reconnect in `_ensure_connected` with backoff. Watch loop detects disconnect and alerts. | Open positions lose bracket protection overnight |
| 2 | **Event-driven fills** | Replace `sleep(2)` with callback-based fill detection using `ib_async` event system | Missed fills → stale order status → reconciliation drift |
| 3 | **Partial fills** | Handle `orderStatus.filled < totalQuantity`. Update shadow_trades with actual filled qty. Log partial fills separately. | Position size mismatch → incorrect P&L calculation |
| 4 | **IB error codes** | Map common IB error codes (110=invalid price, 135=can't find order, 200=no security, 201=order rejected, 202=order cancelled) to specific handling | Generic error handling misses recoverable situations |
| 5 | **Order status mapping** | Map IB statuses (PreSubmitted, Submitted, Filled, Cancelled, Inactive, ApiPending, ApiCancelled, Error) to normalized statuses (pending, filled, cancelled, rejected) | Status confusion → phantom orders |
| 6 | **Market data line management** | Track active subscriptions, cancel before requesting new ones, respect 100-line limit | Silent failures when hitting data line limit |
| 7 | **Extended hours behavior** | Add `outsideRth=False` to all orders to prevent extended-hours fills | Unexpected fills during pre/after-market |
| 8 | **Connection timeout tuning** | Increase timeout for account summary (can take 5-10s on slow Gateway startups) | Timeout during normal operation |
| 9 | **OCA group integrity** | Verify OCA group survives Gateway restart — if not, resubmit stops on reconnect | Stop-loss protection lost after Gateway restart |
| 10 | **Duplicate order prevention** | Check for existing open orders before submitting new bracket | Double-entry on retry |
| 11 | **Graceful shutdown** | Disconnect IB on watch loop shutdown, don't leave orphaned connections | Connection slot consumed after crash |

### Key Implementation Details

**Gateway Reset Handler (Gap 1):**

```python
def _ensure_connected(self):
    """Lazy connect with exponential backoff for Gateway restarts."""
    if self._ib is not None and self._ib.isConnected():
        return
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            from ib_async import IB
            self._ib = IB()
            self._ib.connect(self._host, self._port, 
                           clientId=self._client_id, timeout=self._timeout)
            logger.info("[IB] Connected (attempt %d)", attempt + 1)
            
            # After reconnect: verify open orders still have stops
            self._verify_bracket_integrity()
            return
        except Exception as e:
            wait = 2 ** attempt  # 1, 2, 4 seconds
            logger.warning("[IB] Connect attempt %d failed: %s (retry in %ds)", 
                         attempt + 1, e, wait)
            import time
            time.sleep(wait)  # OK here — not connected yet, no event loop
    
    self._ib = None
    raise ConnectionError(f"IB Gateway unreachable after {max_retries} attempts")
```

**Partial Fill Handler (Gap 3):**

```python
# In place_bracket_order, after self._ib.sleep(2):
if parent_trade.orderStatus.filled < quantity:
    filled = int(parent_trade.orderStatus.filled)
    if filled > 0:
        logger.warning("[IB] Partial fill for %s: %d/%d shares", 
                      ticker, filled, quantity)
        # Update the child orders to match filled quantity
        # IB auto-adjusts OCA children for partial fills
    else:
        # Zero fill after 2s — order may be pending
        logger.info("[IB] Order for %s still pending after 2s", ticker)
```

**Order Status Mapping (Gap 5):**

```python
IB_STATUS_MAP = {
    "presubmitted": "pending",
    "submitted": "pending",
    "filled": "filled",
    "cancelled": "cancelled",
    "inactive": "rejected",
    "apipending": "pending",
    "apicancelled": "cancelled",
    "error": "rejected",
}
```

### Tests (15 new)

| Test | Gap |
|------|-----|
| `test_reconnect_with_backoff` | 1 |
| `test_reconnect_verifies_brackets` | 1 |
| `test_partial_fill_updates_quantity` | 3 |
| `test_zero_fill_returns_pending` | 3 |
| `test_error_code_110_invalid_price` | 4 |
| `test_error_code_201_rejected` | 4 |
| `test_status_mapping_all_values` | 5 |
| `test_status_unknown_defaults_pending` | 5 |
| `test_market_data_line_tracking` | 6 |
| `test_outside_rth_false` | 7 |
| `test_account_summary_timeout_retry` | 8 |
| `test_oca_integrity_after_reconnect` | 9 |
| `test_duplicate_order_prevention` | 10 |
| `test_graceful_disconnect_on_shutdown` | 11 |
| `test_gateway_down_during_trade` | 1, cross-cutting |

### Deep Research Needed ⚠️

Before executing this sprint, deep research should address:

1. **IB OCA group behavior across Gateway restarts** — Does the OCA group survive? Do child orders (stop/target) remain active when the parent is filled and Gateway restarts? IB documentation is ambiguous. This determines whether Gap 9 is a real risk or theoretical.

2. **IB paper trading fill simulation accuracy** — Does IB paper simulate realistic fills (bid/ask crossing, partial fills, slippage) or assume instant midpoint fills? This affects whether our shadow comparison data is meaningful.

3. **ib_async event callback patterns** — The library supports `ib.orderStatusEvent += handler` for real-time fill notifications. What's the best pattern for integrating this with our polling-based architecture? Do we need to run the IB event loop on a separate thread?

### Ralph Loop Findings

**Pass 1:** Gap 7 (`outsideRth=False`) needs to be set on EVERY order type — bracket parent, bracket children, market orders, exit orders. Easy to miss on the child orders in `bracketOrder()` because they're generated by IB's helper function.

**Pass 2:** Gap 9 (OCA integrity) is the scariest gap. If Gateway restarts and the OCA group breaks, a filled entry could lose its stop-loss protection. The `_verify_bracket_integrity()` function after reconnect must check every open IB trade and resubmit stops if missing. This is the most complex piece of the sprint.

**Pass 3:** Gap 4 (error codes) — IB sends errors via the `ib.errorEvent` callback, not as return values. The current synchronous code doesn't listen for these. The production hardening sprint should add an error event handler that logs IB errors and, for critical ones (connection lost, order rejected), triggers immediate action.

---

# SPRINT IB-5: Paper Trading Activation

**Depends on:** IB-4 merged + all IB tests passing + Gateway running stable for 7 days
**Priority:** MEDIUM (gated on IB-4)
**Estimated CC time:** 3-4 hours (mostly config + documentation)

## Design Spec

### Problem

Everything is built and tested. This sprint is the cutover — enabling IB paper trading alongside Alpaca, verifying it works in production, and establishing the monitoring baseline for the 30-day stability gate.

### Activation Checklist (Human + System)

**Pre-activation (Ryan, manual):**

1. Install IB Gateway on Windows 11
2. Configure paper account (port 4002)
3. Enable auto-restart in Gateway settings
4. Verify Gateway starts and connects: `python -c "from src.trading.ib_broker import IBBroker; b = IBBroker(); b._ensure_connected(); print('Connected:', b.is_connected())"`
5. Set config:
```yaml
live_trading:
  ib:
    shadow_mode: false
    paper_routing: true
    paper_routing_threshold: 80
    host: "127.0.0.1"
    port: 4002
    client_id: 1
```

**Activation (CC sprint):**

1. **Gateway setup validation script** — `scripts/validate_ib_gateway.py`
   - Connects to Gateway
   - Checks account type (paper vs live — MUST be paper)
   - Verifies contract qualification for 10 S&P 100 tickers
   - Checks buying power > $0
   - Verifies market data snapshot works
   - Prints comprehensive status report

2. **IB monitoring dashboard card** — Add to Health page:
   - Gateway connection status (connected/disconnected/not configured)
   - Last successful connection timestamp
   - Paper routing threshold
   - IB paper trade count (today / total)
   - IB reconnection count (today)

3. **Daily IB health report** — Add to EOD digest email:
   - IB connection uptime % for the day
   - Trades routed to IB vs Alpaca
   - Any IB errors or fallbacks
   - Bracket health check results

4. **Gateway restart alerting** — Telegram notification when:
   - Gateway disconnects during market hours
   - Reconnection succeeds after disconnect
   - Reconnection fails after 3 attempts
   - Already partially scaffolded in watch loop

5. **30-day stability tracking** — New table or column:
   - Daily uptime percentage
   - Daily trade count on IB
   - Daily error count
   - Running 30-day averages
   - Gate: 30 consecutive days with >95% uptime

6. **IB Gateway Setup Guide** — `docs/operations/ib-gateway-setup.md`
   - Download and install instructions (Windows 11)
   - Paper account configuration
   - Auto-restart settings
   - Firewall considerations (port 4002 local only)
   - Daily reset behavior (11:45 PM ET)
   - Weekend behavior (Gateway stays connected, markets closed)
   - Troubleshooting common issues

### Tests (5 new)

| Test | What |
|------|------|
| `test_validate_gateway_paper_account` | Validation script detects paper vs live |
| `test_validate_gateway_contract_check` | Contract qualification for S&P 100 subset |
| `test_stability_tracking_records_uptime` | Daily uptime logged correctly |
| `test_gateway_restart_alert_sent` | Telegram fires on disconnect/reconnect |
| `test_fallback_to_alpaca_on_gateway_down` | Trades route to Alpaca when IB unavailable |

### Ralph Loop Findings

**Pass 1:** The validation script MUST check account type. If someone accidentally configures port 4001 (live), the script should refuse to proceed and print a prominent warning. This is a safety-critical check.

**Pass 2:** The 30-day stability gate from Strategy Decision #25 needs precise definition: what counts as "stable"? Proposed: >95% uptime during market hours (9:30-4:00 ET), <5 reconnection events per day, zero lost bracket protections. These criteria should be configurable.

**Pass 3:** The Gateway setup guide must include the daily reset behavior explicitly — new users don't expect their trading connection to drop every night at 11:45 PM. The guide should explain that this is normal, the system auto-reconnects, and open orders are preserved on IB's servers.

---

# DEEP RESEARCH NEEDS

Before executing IB-4 (Production Hardening), the following questions should be answered via deep research:

| # | Question | Why It Matters | Suggested Research Prompt |
|---|----------|---------------|--------------------------|
| 1 | **Do IB OCA groups survive Gateway restarts?** | If not, filled entries lose stop-loss protection overnight during the 11:45 PM reset. This is the highest-risk IB-specific issue. | "IB OCA group behavior across TWS Gateway restarts — do child orders (stop-loss, take-profit) remain active when the parent is filled and Gateway disconnects and reconnects? Include ib_async / ib_insync community experience." |
| 2 | **How accurate is IB paper trading fill simulation?** | If IB paper simulates instant midpoint fills, our shadow comparison data is misleading. Need to understand: does IB paper model bid-ask spread, partial fills, and queue priority? | "Interactive Brokers paper trading fill simulation accuracy 2025-2026 — does IB paper account simulate realistic execution (spread, partial fills, slippage) or use simplified midpoint fills?" |
| 3 | **What's the best ib_async event-driven pattern for fill detection?** | Current `sleep(2)` is brittle. Need to understand whether we should use callbacks (`orderStatusEvent`), polling with `sleep()`, or a hybrid. Threading implications. | "ib_async event-driven order fill detection patterns — orderStatusEvent callbacks vs polling with ib.sleep(). Threading considerations for integrating with a synchronous application." |
| 4 | **IB Gateway Windows 11 stability patterns** | Anecdotal reports of Gateway crashing on Windows. Need to understand: how stable is Gateway on Windows 11 over 30+ days? Common failure modes? | "Interactive Brokers Gateway stability on Windows 11 2025-2026 — common failure modes, auto-restart reliability, memory leaks, daily reset behavior, 30-day continuous operation experience." |

These can be run as Claude Deep Research queries before IB-4 is written as a sprint prompt. The answers directly affect the implementation details of Gaps 1, 2, 3, and 9.

---

# UPDATED SPRINT QUEUE

## Execution Order

### Tier 1: Execute Now (This Week)

| # | Sprint | Status | Who | Time |
|---|--------|--------|-----|------|
| 1 | Monday pre-market deploy | Ready | Ryan | 30 min |
| 2 | Manual backfill — export prompts | Ready (code merged) | Ryan | 30 min |
| 3 | Manual backfill — generate examples | Ongoing | Ryan | 3-4 weeks evenings |
| 4 | IB-1: Tests + Shadow Mode | Sprint written | CC | 6-8 hrs |

### Tier 2: Execute Next (Next Week)

| # | Sprint | Status | Who | Depends On |
|---|--------|--------|-----|-----------|
| 5 | IB-2: Shadow Dashboard | Sprint written | CC | IB-1 merged |
| 6 | IB deep research (4 questions) | Flagged above | Claude Deep Research | Nothing |
| 7 | Roadmap updates | Sprint written, CC may have executed | CC | Nothing |

### Tier 3: Execute After Shadow Validation (2-3 Weeks)

| # | Sprint | Status | Who | Depends On |
|---|--------|--------|-----|-----------|
| 8 | IB-3: Dual-Execution Routing | Spec in this doc | CC | IB-1 + IB-2 merged + 1-2 weeks shadow data |
| 9 | IB-4: Production Hardening | Spec in this doc | CC | IB-3 merged + deep research answers |
| 10 | IB-5: Paper Trading Activation | Spec in this doc | CC | IB-4 merged + 7 days Gateway stable |

### Tier 4: After Backfill + IB Paper Stable (Month 2)

| # | Sprint | Status | Who | Depends On |
|---|--------|--------|-----|-----------|
| 11 | v2.0.0 model retrain | Not written | CC + Ryan | 400+ backfill examples imported |
| 12 | IB dual-execution live (actual routing) | Not written | CC | IB-5 passed 30-day gate |

### Tier 5: Stale Feature Branches (Evaluate / Abandon)

| Branch | Sprint | Recommendation |
|--------|--------|---------------|
| `feat/gap-assessment-top3` | Embedding leakage, Bayesian weights, two-tier RS | Review — may be outdated by recent changes |
| `feat/model-performance` | Model performance dashboard | Review — useful but low priority |
| `feat/simulation-engine` | 13-scenario simulation | Review — already partially deployed? |
| `feat/ui-bloomberg` | Bloomberg UI redesign | Review — cosmetic, defer |

### Open GitHub Issues (2)

| # | Issue | Resolution |
|---|-------|-----------|
| #367 | WatchLoop god object (2,003 lines) | Tech debt sprint — not blocking anything, schedule after IB sequence |
| #368 | IB broker zero test coverage | Closed by IB-1 sprint |

---

# FULL IB SPRINT FILE INDEX

| Sprint | Document | Lines | Status |
|--------|----------|-------|--------|
| IB-1: Tests + Shadow Mode | `docs/sprints/sprint-ib-tests-shadow.md` | 1,111 | Written, ready for CC |
| IB-2: Shadow Dashboard | `docs/sprints/sprint-ib-shadow-dashboard.md` | 472 | Written, ready for CC |
| IB-3: Dual-Execution Routing | This document (Section 1) | — | Spec complete, sprint prompt needed after IB deep research |
| IB-4: Production Hardening | This document (Section 2) | — | Spec complete, blocked on deep research |
| IB-5: Paper Trading Activation | This document (Section 3) | — | Spec complete, blocked on IB-4 |

**Note:** IB-3, IB-4, and IB-5 have design specs and Ralph-looped test matrices in this document. Full CC sprint prompts (with exact code, file paths, commit messages) will be written AFTER:
1. IB-1 and IB-2 ship and we have real shadow data
2. The 4 deep research questions are answered
3. The answers may change implementation details significantly (especially for IB-4 Gaps 1, 3, 9)

Writing full sprint prompts now for IB-4 without knowing whether OCA groups survive Gateway restarts would be premature — the answer to that question determines whether Gap 9 is a 5-line check or a 100-line bracket resubmission system.
