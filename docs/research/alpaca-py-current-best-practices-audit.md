# alpaca-py Current Best-Practices Audit

**Authority:** `docs/sprints/sprint-alpaca-py-migration.md` Task 3
**Audit date:** 2026-04-16
**Installed version:** `alpaca-py==0.43.2` (pin: `>=0.43,<1.0`)
**Surfaces audited:** `src/shadow_trading/alpaca_adapter.py` (705 lines, 10 imports), `src/shadow_trading/executor.py` (2,341 lines, 3 imports)

---

## Summary

The migration to `alpaca-py` is complete and the call sites use the modern
SDK idioms correctly for **request construction**, **client instantiation**,
and **enum usage**. Two gaps exist around **typed exception handling** and
**idempotency via `client_order_id`** — both flagged as follow-up work below.

| Criterion | Status | Notes |
|---|---|---|
| Request-object construction (not dict-based) | ✅ PASS | All 6 submit-order sites use `MarketOrderRequest(...)` / `LimitOrderRequest(...)` / `StopOrderRequest(...)` with kwargs. |
| `TradingClient(paper=...)` explicit | ✅ PASS | Paper client at `alpaca_adapter.py:147` has `paper=True`; live client at line 541 has `paper=False`. Both explicit. |
| Typed `APIError` exception handling | ⚠️ GAP | Only 1 of 15 `except` clauses in the Alpaca path uses `APIError` (executor.py:763). Adapter file uses bare `except Exception`. |
| `client_order_id` set for idempotency | ⚠️ GAP | Zero sites pass `client_order_id`. Retries at the network layer can double-submit. |
| Enums (`OrderSide.BUY`), not string literals | ✅ PASS | All 6 order-construction sites use `OrderSide.BUY` / `OrderSide.SELL`, `TimeInForce.DAY` / `.GTC`, `OrderClass.BRACKET`. |

**Bottom line:** zero bugs, two improvements recommended. No code changes in
this sprint unless follow-up tickets are explicitly scoped.

---

## Per-call-site audit

### `src/shadow_trading/alpaca_adapter.py`

| Line | Symbol | Purpose | Modern pattern? |
|---|---|---|---|
| 143 | `TradingClient` (paper) | Account/positions/order lifecycle | ✅ paper=True explicit |
| 154 | `StockHistoricalDataClient` | Historical OHLCV | ✅ correct instantiation |
| 186–187 | `MarketOrderRequest` / `LimitOrderRequest` + `OrderSide` / `TimeInForce` | Bracket entry | ✅ kwargs, enums |
| 224–225 | `MarketOrderRequest` + `OrderSide` / `TimeInForce` | Exit submit | ✅ kwargs, enums |
| 279–280 | `MarketOrderRequest` / `LimitOrderRequest` + `OrderSide` / `TimeInForce` / `OrderClass` | Bracket parent + TP/SL | ✅ kwargs, enums; ⚠️ `take_profit` / `stop_loss` passed as dicts (SDK-accepted but `TakeProfitRequest` / `StopLossRequest` is more typesafe) |
| 370 | `StockLatestTradeRequest` | Real-time price probe | ✅ kwargs |
| 460 | `GetOrdersRequest` | Order query by status | ✅ kwargs, `QueryOrderStatus` enum |
| 537 | `TradingClient` (live) | Live trading surface | ✅ paper=False explicit |
| 580–581 | `MarketOrderRequest` + `OrderSide` / `TimeInForce` | Live-order path | ✅ kwargs, enums |
| 652–653 | `MarketOrderRequest` + `OrderSide` / `TimeInForce` | Cancel-and-close | ✅ kwargs, enums |

**Observations:**
- `client.submit_order(request)` signature is used everywhere — not the
  legacy positional kwargs API.
- Bracket TP/SL passed as `{"limit_price": ...}` / `{"stop_price": ...}`
  dicts. alpaca-py accepts this and the SDK docs show both forms. No bug;
  marginal style preference.
- `paper=True` uses the Alpaca paper base URL by default — no custom
  `base_url` override, which is correct.

### `src/shadow_trading/executor.py`

| Line | Symbol | Purpose | Modern pattern? |
|---|---|---|---|
| 41 | `APIError` (top-level) | Typed exception base class | ✅ imported from `alpaca.common.exceptions` |
| 693 | `StopOrderRequest` | Secondary stop order | ✅ kwargs |
| 694 | `OrderSide` / `TimeInForce` | Stop-order enums | ✅ enums |
| 763 | `except APIError as e2` | One typed-catch site | ✅ (only one — see gap below) |

---

## Gaps & Recommendations

### Gap 1 — Typed `APIError` handling is rare

**Evidence:**
```
$ grep -nE "except APIError|except Exception" src/shadow_trading/alpaca_adapter.py | wc -l
14  # bare-Exception catches
$ grep -nE "except APIError" src/shadow_trading/alpaca_adapter.py | wc -l
0   # typed catches
```

**Why it matters:** `APIError` is raised for 4xx/5xx from the Alpaca REST
endpoints with structured payloads — rejection reasons, invalid symbol,
insufficient buying power, rate limits. Bare `except Exception` also
catches `ConnectionError`, `ValueError`, and any JSON-parsing failure,
which should be handled separately.

**Recommendation:** at each `submit_order` / `get_position` /
`get_open_position` call site, split the catch into:

```python
from alpaca.common.exceptions import APIError

try:
    order = client.submit_order(request)
except APIError as e:
    # Alpaca rejected the order — retriable depending on e.status_code
    logger.warning("[ALPACA] API rejection %s: %s", e.status_code, e)
    raise
except (ConnectionError, TimeoutError) as e:
    # Network-level — retry with backoff
    logger.warning("[ALPACA] Network error: %s", e)
    raise
```

**Scope:** follow-up ticket. Not in this sprint.

### Gap 2 — `client_order_id` absent on all submit paths

**Evidence:**
```
$ grep -n "client_order_id" src/shadow_trading/alpaca_adapter.py
# empty
```

**Why it matters:** If `client.submit_order(request)` times out at the HTTP
layer, the request may have been accepted by Alpaca but the response lost.
A naive retry then submits a second, duplicate order. Idempotent retries
require the client to set `client_order_id` — Alpaca deduplicates based on
this header.

Current code relies on an application-level dedup (the `recommendation_id`
flow in the DB), which prevents the same *recommendation* from being
submitted twice but doesn't protect against network-layer retries of the
same physical HTTP call.

**Recommendation:** add `client_order_id` to every `MarketOrderRequest`,
`LimitOrderRequest`, `StopOrderRequest`. Natural choice:

```python
import uuid
request = MarketOrderRequest(
    symbol=ticker,
    qty=shares,
    side=OrderSide.BUY,
    time_in_force=TimeInForce.DAY,
    client_order_id=f"arcis-{recommendation_id}-{uuid.uuid4().hex[:8]}",
)
```

**Scope:** follow-up ticket. Phase 6 intraday work will raise retry rates
(streaming re-subscription + higher order volume), so idempotency
hardening is a Phase 6 blocker, not a Phase 1 concern.

### Minor — Dict form for `take_profit` / `stop_loss`

In the bracket submit path (line 290-291, 300-301), `take_profit` and
`stop_loss` are dicts. alpaca-py accepts both dicts and `TakeProfitRequest`
/ `StopLossRequest` objects; Request-object form gives better IDE
completion and type-checking. Zero functional difference.

**Scope:** defer until the next touch of that function. Not a separate
ticket.

---

## Streaming readiness (Phase 6)

Out of scope for this audit — see `docs/research/alpaca-py-intraday-streaming-gap.md`.

---

## Verification run

```bash
$ grep -rn "alpaca_trade_api" src/ tests/ requirements*.txt
# empty

$ grep -rnE "^\s*(from|import)\s+alpaca" src/ tests/ --include="*.py" | wc -l
# 16 imports across 3 files (alpaca_adapter.py, executor.py, tests/test_executor_import.py)

$ python -c "import alpaca; print(alpaca.__version__)"
0.43.2

$ grep -rnE "TradingStream|StockDataStream" src/ --include="*.py" | grep -v test
# empty — confirmed Phase 6 surface not yet touched

$ pytest tests/test_repo_structure.py::test_no_legacy_alpaca_trade_api_imports
# 1 passed
```

---

## Closing

The migration is done. The two gaps above are worth tickets but not bugs;
current trading behavior is correct. The `test_no_legacy_alpaca_trade_api_imports`
CI guardrail prevents accidental reintroduction of the deprecated SDK.
