# IB Integration: Complete Sprint Lineup (v2 — Updated After CC Gap Analysis)

**Date:** April 11, 2026
**Author:** Claude (Opus 4.6)
**Supersedes:** `sprint-ib-sequence-3-4-5.md` (numbering shifted — old IB-3/4/5 are now IB-4/5/6)

---

## Sprint Sequence Overview

| Sprint | Name | Doc | Status | Blocker | CC Time |
|--------|------|-----|--------|---------|---------|
| **IB-1** | Tests + Shadow Mode | `sprint-ib-tests-shadow.md` | ✅ Written | None | 6-8 hrs |
| **IB-2** | Critical Structural Fixes | **This document (below)** | ✅ Written | IB-1 merged | 4-6 hrs |
| **IB-3** | Shadow Dashboard | `sprint-ib-shadow-dashboard.md` | ✅ Written | IB-1 merged | 3-4 hrs |
| **IB-4** | Dual-Execution Routing | `sprint-ib-sequence-3-4-5.md` §1 | Spec only | IB-2 + deep research | 6-8 hrs |
| **IB-5** | Production Hardening | `sprint-ib-sequence-3-4-5.md` §2 | Spec only | Deep research (4 Qs) | 8-10 hrs |
| **IB-6** | Paper Trading Activation | `sprint-ib-sequence-3-4-5.md` §3 | Spec only | IB-5 + 7-day stable | 3-4 hrs |

**Deep research:** 4 prompts running now → answers inform IB-4 and IB-5 sprint prompts.

**Execution order:** IB-1 → IB-2 → IB-3 (can parallel with IB-2) → wait for deep research → IB-4 → IB-5 → IB-6.

---

## What Changed Since v1

CC performed an exploratory analysis and found **4 critical runtime bugs** and **7 important gaps** in the existing IB integration. These are in `executor.py`, `reconcile.py`, `governor.py`, and `ib_broker.py` — not in the shadow mode path. IB-1 (tests + shadow) is unaffected, but a new **IB-2 sprint** is needed before dual-execution routing.

---

# SPRINT IB-2: Critical IB Structural Fixes

> **Branch:** `fix/ib-structural`
> **Priority:** CRITICAL — every gap is a runtime crash or silent failure on the IB path
> **Depends on:** IB-1 merged (tests must exist before fixing production code)
> **Estimated CC time:** 4-6 hours
> **Closes:** Contributes to #368
>
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b fix/ib-structural
> python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
> ```

---

## Task 1: Fix `get_live_broker()` called without config

**File:** `src/shadow_trading/executor.py` (~line 814)

**Bug:** `get_live_broker()` is called without arguments. The function signature requires `config: dict`.

**Fix:**
```python
# BEFORE (line 814):
live_broker = get_live_broker()

# AFTER:
live_broker = get_live_broker(load_config())
```

Verify `load_config` is already imported (it is — used elsewhere in executor.py).

**Test:** Add to `tests/test_live_trading.py`:
```python
def test_check_and_manage_calls_get_live_broker_with_config(self, ...):
    """get_live_broker must receive config dict, not be called bare."""
    # Mock get_live_broker, call check_and_manage_open_trades with source_filter="live"
    # Verify get_live_broker was called with a dict argument
```

**Commit:** `fix(executor): pass config to get_live_broker — fixes TypeError on live path`

---

## Task 2: Fix `get_positions()` → `get_all_positions()`

**File:** `src/shadow_trading/executor.py` (~line 816)

**Bug:** Calls `live_broker.get_positions()` which doesn't exist on `BrokerAdapter`. The correct method is `get_all_positions()`.

**Fix:**
```python
# BEFORE (line 816):
_alpaca_tickers = {p["symbol"] for p in live_broker.get_positions()}

# AFTER:
_live_positions = live_broker.get_all_positions()
_alpaca_tickers = {p.ticker for p in _live_positions}
```

Note the double fix: `get_positions()` → `get_all_positions()` AND `p["symbol"]` → `p.ticker` (BrokerPosition is a dataclass with `.ticker`, not a dict with `["symbol"]`).

**Test:** Add to `tests/test_live_trading.py`:
```python
def test_live_position_check_uses_broker_adapter_interface(self, ...):
    """Position check must use get_all_positions() returning BrokerPosition objects."""
    # Mock broker with get_all_positions returning [BrokerPosition(ticker="AAPL", ...)]
    # Verify _alpaca_tickers contains "AAPL"
```

**Commit:** `fix(executor): get_all_positions + BrokerPosition.ticker — fixes AttributeError on live path`

---

## Task 3: Fix bracket order construction + store child order IDs

**File:** `src/trading/ib_broker.py` (~line 110-155)

**Bugs (3 combined — from CC gap analysis + deep research):**
1. Child order IDs discarded — bracket monitoring blind to IB
2. `outsideRth` not set — GTC stops won't execute outside regular trading hours, leaving positions unprotected overnight (**deep research finding: "multiple community reports document positions left unprotected overnight because this flag was missing"**)
3. `OcaType` not set — default allows dual-fill race condition in fast markets (**deep research: "use OcaType 3 (with block/overfill protection) for bracket children"**)
4. `orderId` is session-specific — must store `permId` for cross-session tracking (**deep research: "orderId resets on reconnect, permId is persistent and unique account-wide"**)

**Fix — BrokerOrder dataclass** (add to `src/trading/broker_interface.py`):

```python
@dataclass
class BrokerOrder:
    # ... existing fields ...
    child_order_ids: list[str] | None = None  # IB bracket: [take_profit_permId, stop_loss_permId]
    perm_id: str | None = None                # IB permanent order ID (survives sessions)
```

**Fix — `place_bracket_order()` in `ib_broker.py`:**

```python
    def place_bracket_order(self, ticker, quantity, take_profit_price,
                            stop_loss_price, limit_price=None):
        self._ensure_connected()
        contract = self._make_contract(ticker)
        self._ib.qualifyContracts(contract)

        bracket = self._ib.bracketOrder(
            action="BUY",
            quantity=quantity,
            limitPrice=round(limit_price, 2) if limit_price else 0,
            takeProfitPrice=round(take_profit_price, 2),
            stopLossPrice=round(stop_loss_price, 2),
        )

        # If no limit price, convert parent to market order
        if not limit_price:
            bracket[0].orderType = "MKT"
            bracket[0].lmtPrice = 0

        # RESEARCH FINDINGS — 3 mandatory settings:
        for order in bracket:
            order.tif = "GTC"              # Exits persist across sessions
            order.outsideRth = True         # Protect positions outside market hours
        # OcaType 3 = block + overfill protection (prevents dual-fill race)
        for order in bracket[1:]:           # Children only
            order.ocaType = 3

        # Place the bracket (parent + children)
        trades = []
        for order in bracket:
            trade = self._ib.placeOrder(contract, order)
            trades.append(trade)

        parent_trade = trades[0]
        self._ib.sleep(2)

        # Store PERMANENT IDs (not session-specific orderId)
        child_perm_ids = [str(t.order.permId) for t in trades[1:]] if len(trades) > 1 else None

        return BrokerOrder(
            order_id=str(parent_trade.order.orderId),
            perm_id=str(parent_trade.order.permId),
            ticker=ticker,
            side="buy",
            quantity=quantity,
            order_type="bracket",
            status=parent_trade.orderStatus.status.lower(),
            filled_avg_price=parent_trade.orderStatus.avgFillPrice or None,
            filled_qty=int(parent_trade.orderStatus.filled) if parent_trade.orderStatus.filled else 0,
            stop_price=stop_loss_price,
            take_profit_price=take_profit_price,
            child_order_ids=child_perm_ids,
            broker="ib",
        )
```

**Schema change:** Add columns to `shadow_trades`:

```python
ColumnDef("ib_child_order_ids", "TEXT", description="JSON list of IB child order permIds [take_profit, stop_loss]"),
ColumnDef("ib_perm_id", "TEXT", description="IB permanent order ID — survives Gateway restarts"),
```

**Executor change:** When storing IB bracket trades, save IDs:

```python
if broker_order.child_order_ids:
    trade_data["ib_child_order_ids"] = json.dumps(broker_order.child_order_ids)
if broker_order.perm_id:
    trade_data["ib_perm_id"] = broker_order.perm_id
```

**Tests:**
```python
def test_bracket_order_returns_child_perm_ids(self):
    """place_bracket_order must return child permIds for cross-session tracking."""

def test_bracket_all_outside_rth(self):
    """All 3 bracket orders must have outsideRth=True."""

def test_bracket_children_oca_type_3(self):
    """Child orders must have ocaType=3 (block/overfill protection)."""

def test_bracket_returns_perm_id(self):
    """BrokerOrder.perm_id populated from parent trade."""
```

**Commit:** `fix(ib): bracket hardening — outsideRth, OcaType 3, permId, child order tracking`

---

## Task 4: Make bracket exit monitoring broker-aware

**File:** `src/shadow_trading/executor.py` (~line 960-980)

**Bug:** Exit detection calls `alpaca_adapter.get_order_status()` unconditionally. IB trades' bracket fills are invisible.

**Fix:** Route through broker factory for live/IB trades, keep Alpaca direct for paper:

```python
# BEFORE:
if trade.get("order_type") == "bracket" and trade.get("alpaca_order_id"):
    from src.shadow_trading.alpaca_adapter import get_order_status
    order_status = get_order_status(trade["alpaca_order_id"])

# AFTER:
if trade.get("order_type") == "bracket" and trade.get("alpaca_order_id"):
    if trade.get("source") == "live":
        # Route through broker abstraction for live trades
        from src.trading.broker_factory import get_live_broker
        broker = get_live_broker(load_config())
        try:
            broker_order = broker.get_order_status(trade["alpaca_order_id"])
            order_status = {
                "status": broker_order.status,
                "filled_avg_price": broker_order.filled_avg_price,
                "filled_qty": broker_order.filled_qty,
            }
        except ValueError:
            order_status = {"status": "unknown"}
    else:
        # Paper trades use Alpaca directly
        from src.shadow_trading.alpaca_adapter import get_order_status
        order_status = get_order_status(trade["alpaca_order_id"])
```

**Also check IB child orders** when the parent status is ambiguous:

```python
# After checking parent status, also check child orders for IB brackets
if trade.get("source") == "live" and trade.get("ib_child_order_ids"):
    child_ids = json.loads(trade["ib_child_order_ids"])
    for child_id in child_ids:
        try:
            child_order = broker.get_order_status(child_id)
            if child_order.status == "filled":
                exit_price = child_order.filled_avg_price
                # Determine if this was stop or target based on child index
                # child_ids[0] = take_profit, child_ids[1] = stop_loss
                bracket_exit = True
                exit_reason = "target_1_hit" if child_id == child_ids[0] else "stop_hit"
                break
        except ValueError:
            continue
```

**Test:** Add to `tests/test_ib_broker.py` or `tests/test_bracket_safety.py`:
```python
def test_live_bracket_exit_uses_broker_factory(self, ...):
    """Live trade bracket exit detection routes through broker factory, not Alpaca."""
    # Mock trade with source="live", mock broker.get_order_status
    # Verify alpaca_adapter.get_order_status is NOT called

def test_ib_child_order_fill_detected(self, ...):
    """IB child order (stop/target) fill detection works via child_order_ids."""
    # Mock trade with ib_child_order_ids, mock broker returning filled child
    # Verify bracket_exit=True and correct exit_reason
```

**Commit:** `fix(executor): broker-aware bracket exit monitoring — IB fills now detectable`

---

## Task 5: Fix `_retry_exit` to use broker-aware cancel

**File:** `src/shadow_trading/executor.py` (~line 730)

**Bug:** `cancel_paper_order()` always calls Alpaca, even for live/IB trades.

**Fix:**
```python
# BEFORE (line 730):
cancel_paper_order(pending_order_id)

# AFTER:
if trade.get("source") == "live":
    from src.trading.broker_factory import get_live_broker
    broker = get_live_broker(load_config())
    broker.cancel_order(pending_order_id)
else:
    cancel_paper_order(pending_order_id)
```

**Test:**
```python
def test_retry_exit_cancels_via_broker_for_live(self, ...):
    """Live trade retry uses broker.cancel_order, not cancel_paper_order."""
```

**Commit:** `fix(executor): broker-aware cancel in _retry_exit — IB orders no longer dangling`

---

## Task 6: Fix risk governor equity source

**File:** `src/risk/governor.py`

**Bug:** `get_current_equity()` always computes from paper shadow_trades P&L. IB live positions sized against wrong balance.

**Fix:** When `live_trading.enabled` and `broker == "ib"`, get equity from IB account:

```python
def get_current_equity(config: dict | None = None, db_path: str = DB_PATH) -> float:
    if config is None:
        config = load_config()

    live_cfg = config.get("live_trading", {})

    # For live IB trading, use the broker's reported equity
    if live_cfg.get("enabled") and live_cfg.get("broker") == "ib":
        try:
            from src.trading.broker_factory import get_live_broker
            broker = get_live_broker(config)
            if broker.is_connected():
                acct = broker.get_account()
                return acct.equity
        except Exception as e:
            logger.warning("[RISK] Failed to get IB equity, falling back to DB: %s", e)

    # Default: compute from DB (paper or Alpaca live)
    starting_capital = ...  # existing code
```

**Test:**
```python
def test_equity_from_ib_when_live_ib(self, ...):
    """Risk governor uses IB account equity when broker is IB."""

def test_equity_falls_back_to_db_when_ib_down(self, ...):
    """If IB is disconnected, fall back to DB-computed equity."""
```

**Commit:** `fix(governor): use IB account equity when live broker is IB`

---

## Task 7: Fix reconciler cancel to be broker-aware

**File:** `src/shadow_trading/reconcile.py` (~line 410)

**Bug:** `cancel_orders_for_ticker()` always calls Alpaca. IB stale trade orders not cancelled.

**Fix:**
```python
# BEFORE (line 410):
from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
cancelled = cancel_orders_for_ticker(ticker)

# AFTER:
if trade_source == "live":
    try:
        from src.trading.broker_factory import get_live_broker
        broker = get_live_broker(load_config())
        # IB doesn't have cancel_orders_for_ticker — cancel individually
        for order_id in [trade.get("alpaca_order_id"), trade.get("exit_order_id")]:
            if order_id:
                broker.cancel_order(order_id)
        # Also cancel child orders if IB bracket
        if trade.get("ib_child_order_ids"):
            for child_id in json.loads(trade["ib_child_order_ids"]):
                broker.cancel_order(child_id)
        cancelled = True
    except Exception as e:
        logger.warning("[RECONCILE] IB cancel failed for %s: %s", ticker, e)
        cancelled = False
else:
    from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
    cancelled = cancel_orders_for_ticker(ticker)
```

**Test:**
```python
def test_reconciler_cancels_ib_orders(self, ...):
    """Live IB trades have orders cancelled via broker factory during reconciliation."""
```

**Commit:** `fix(reconcile): broker-aware order cancellation for IB trades`

---

## Task 8: Fix IB position current_price

**File:** `src/trading/ib_broker.py` (lines 225, 239)

**Bug:** `current_price=0.0` hardcoded. IB requires a separate market data request.

**Fix:** Use `get_current_price()` for each position:

```python
def get_position(self, ticker: str) -> Optional[BrokerPosition]:
    self._ensure_connected()
    for pos in self._ib.positions():
        if pos.contract.symbol == ticker:
            # Fetch current price for P&L accuracy
            current = self.get_current_price(ticker) or 0.0
            return BrokerPosition(
                ticker=ticker,
                quantity=int(pos.position),
                avg_cost=float(pos.avgCost),
                current_price=current,
                unrealized_pnl=float(pos.position) * (current - float(pos.avgCost)) if current else 0.0,
                market_value=float(pos.position) * current if current else float(pos.position * pos.avgCost),
                broker="ib",
            )
    return None
```

**Caution:** This adds a market data request per position call. For `get_all_positions()`, batch the price requests to avoid hitting the 100-line limit. If there are >10 positions, skip individual price lookups and use 0.0 with a log warning.

```python
def get_all_positions(self) -> list[BrokerPosition]:
    self._ensure_connected()
    positions = self._ib.positions()
    result = []
    for pos in positions:
        ticker = pos.contract.symbol
        current = 0.0
        if len(positions) <= 10:  # Only fetch prices for small portfolios
            current = self.get_current_price(ticker) or 0.0
        result.append(BrokerPosition(
            ticker=ticker,
            quantity=int(pos.position),
            avg_cost=float(pos.avgCost),
            current_price=current,
            unrealized_pnl=float(pos.position) * (current - float(pos.avgCost)) if current else 0.0,
            market_value=float(pos.position) * current if current else float(pos.position * pos.avgCost),
            broker="ib",
        ))
    return result
```

**Test:**
```python
def test_get_position_fetches_current_price(self, ...):
    """get_position should fetch real price, not return 0.0."""

def test_get_all_positions_batches_when_small(self, ...):
    """get_all_positions fetches prices when <= 10 positions."""

def test_get_all_positions_skips_prices_when_large(self, ...):
    """get_all_positions skips price fetch when > 10 positions."""
```

**Commit:** `fix(ib): fetch current_price in get_position — fixes unrealized P&L calculation`

---

## Task 9: Add ib_async to optional dependencies

**File:** `requirements.txt` or `pyproject.toml`

Add `ib_async` as an optional dependency:

```
# Optional: Interactive Brokers (only needed when live_trading.broker = "ib")
# ib_async>=1.0.0
```

Comment it out — it's optional. But document its existence so the install path is clear.

Also add a startup check in `src/startup_checks.py`:

```python
# Check ib_async availability when IB is configured
if config.get("live_trading", {}).get("broker") == "ib":
    try:
        import ib_async
        checks.append(CheckResult("ib_async_installed", "pass", "ib_async available"))
    except ImportError:
        checks.append(CheckResult("ib_async_installed", "error",
            "ib_async not installed — run: pip install ib_async",
            fix_hint="pip install ib_async --break-system-packages"))
```

**Commit:** `fix(startup): check ib_async availability when IB broker configured`

---

## Task 10: Rename `alpaca_order_id` column (design prep)

**Do NOT rename the column in this sprint** — it's referenced in 50+ locations. Instead, add an alias column:

```python
ColumnDef("broker_order_id", "TEXT", description="Alias for alpaca_order_id — stores order ID from whichever broker executed"),
```

And add a migration note to MASTER.md:

```markdown
**Tech debt:** `alpaca_order_id` column stores IB order IDs too. The column
`broker_order_id` was added as an alias. Future sprint should migrate all
references from `alpaca_order_id` to `broker_order_id` and deprecate the original.
```

**Commit:** `schema: add broker_order_id alias column — prep for alpaca_order_id migration`

---

## Task 11: Tests + Documentation

Run full test suite:
```bash
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
python -m pytest tests/test_ib_broker.py tests/test_ib_shadow.py -v
```

Update:
- `CHANGELOG.md`
- `MASTER.md` — note structural fixes, update IB status

**Commit:** `docs: IB structural fixes changelog + MASTER update`

**Push:**
```bash
git push origin fix/ib-structural
```

---

## Verification Checklist

```bash
# All tests pass
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# The 4 critical bugs are fixed
grep "get_live_broker(load_config())" src/shadow_trading/executor.py  # line ~814
grep "get_all_positions()" src/shadow_trading/executor.py            # line ~816
grep "child_order_ids" src/trading/ib_broker.py                      # bracket returns child IDs
grep "source.*==.*live" src/shadow_trading/executor.py | grep -c "broker_factory"  # bracket exit uses broker

# No file over 400 lines (check ib_broker.py after changes)
wc -l src/trading/ib_broker.py  # should be ~290 (was 271)

# Frontend builds (schema change)
cd frontend && npm run build && cd ..
```

---

## Ralph Loop Findings

**Pass 1:** The `get_all_positions()` fix (Task 2) has a subtle double bug: `get_positions()` → `get_all_positions()` AND `p["symbol"]` → `p.ticker`. BrokerPosition is a dataclass, not a dict. CC's analysis caught the method name but I almost missed the dict-vs-dataclass access pattern.

**Pass 2:** Task 8 (current_price fix) could cause performance issues — `get_current_price()` does `reqMktData` + `sleep(3)` per call. With 10 positions, that's 30 seconds of blocking. Added the 10-position cap with a skip path for larger portfolios.

**Pass 3:** Task ordering is critical — Task 3 must come before Task 4 because Task 4 depends on the `ib_child_order_ids` and `ib_perm_id` columns from Task 3.

**Pass 4 (post-research — ib_async events):** Deep research recommends the **connect/disconnect pattern** for our 15-30 minute polling loop — connect fresh each scan cycle, rebuild state from server via `openTrades()` + `positions()` + `executions()`, disconnect when done. This eliminates stale Trade objects, event loop management, idle connection risks, and memory leaks. Bracket orders execute server-side at IB regardless of API connection. This simplifies IB-5 (Production Hardening) significantly — Gap 2 (event-driven fills) is replaced by fresh-connection state reconstruction.

**Pass 5 (post-research — OCA groups):** Three mandatory bracket settings: `outsideRth=True` on all orders (positions unprotected overnight without it), `OcaType 3` on children (prevents dual-fill race), `permId` for tracking not `orderId` (session-specific). All folded into Task 3.

**Pass 6 (post-research — paper fills):** IB paper fills are pessimistic (end-of-queue limit model), Alpaca paper fills are optimistic (NBBO, no liquidity check). IB paper is the better simulation. Expected paper-to-live drag: 3-15 bps per round-trip for S&P 100. Apply 20% performance buffer before scaling. IB paper has a known quirk: partial fill remainders are REJECTED (not how real exchanges work).

---

# UPDATED FULL TODO QUEUE

## This Week (Tier 1)

| # | Task | Who | Time | Status |
|---|------|-----|------|--------|
| 1 | Monday pre-market deploy | Ryan | 30 min | Ready |
| 2 | Export backfill prompts | Ryan | 30 min | Ready |
| 3 | IB-1: Tests + Shadow Mode | CC | 6-8 hrs | Sprint written |
| 4 | Run IB deep research (4 prompts) | Ryan/Claude | 1 hr | Running now |

## Next Week (Tier 2)

| # | Task | Who | Depends On |
|---|------|-----|-----------|
| 5 | IB-2: Critical Structural Fixes | CC | IB-1 merged |
| 6 | IB-3: Shadow Dashboard | CC | IB-1 merged (can parallel with IB-2) |
| 7 | Begin manual backfill generation | Ryan | Export done |

## Weeks 3-4 (Tier 3)

| # | Task | Who | Depends On |
|---|------|-----|-----------|
| 8 | Incorporate deep research into IB-4/5 sprint prompts | Claude | Research results |
| 9 | IB-4: Dual-Execution Routing | CC | IB-2 + research |
| 10 | Continue backfill generation | Ryan | Ongoing |

## Month 2 (Tier 4)

| # | Task | Who | Depends On |
|---|------|-----|-----------|
| 11 | IB-5: Production Hardening | CC | IB-4 + research |
| 12 | IB-6: Paper Trading Activation | CC | IB-5 + 7-day stable |
| 13 | v2.0.0 model retrain | CC + Ryan | 400+ backfill examples |

## Stale Branches (Evaluate)

| Branch | Recommendation |
|--------|---------------|
| `feat/gap-assessment-top3` | Review — may conflict with recent changes |
| `feat/model-performance` | Review — useful dashboard page |
| `feat/simulation-engine` | Review — already partially deployed? |
| `feat/ui-bloomberg` | Defer — cosmetic |

## Open Issues (2)

| # | Issue | Resolution |
|---|-------|-----------|
| #367 | WatchLoop god object | Tech debt — schedule after IB sequence |
| #368 | IB zero test coverage | Closed by IB-1 + IB-2 |
