# IB Shadow Dashboard + API Routes: Master Implementation Document

**Version:** 1.0 (triple Ralph-looped: spec, implementation plan, sprint prompt)
**Author:** Claude (Opus 4.6)
**Date:** April 11, 2026
**Depends on:** IB Tests + Shadow Mode sprint (feat/ib-tests-shadow must merge first)
**Priority:** MEDIUM — completes the shadow mode feature, not blocking trading

---

# PART 1: DESIGN SPEC

## 1.1 Purpose

The backend IB shadow sprint (feat/ib-tests-shadow) creates `ib_shadow_log` data but provides no way to view it. This sprint adds:
1. Postgres sync for the `ib_shadow_log` table
2. API routes to serve shadow data to the dashboard
3. A new IB Shadow dashboard page showing comparison analytics
4. Health page updates for IB Gateway connection status

## 1.2 Schema Update

The `ib_shadow_log` table definition from the backend sprint needs `sync_to_postgres=True` added (the backend sprint explicitly omitted this — that was wrong, the dashboard reads from Render Postgres).

```python
# In registry.py, update the ib_shadow_log TableDef:
sync_to_postgres=True,
sync_mode="incremental",
sync_time_column="created_at",
sync_pk="shadow_id",
```

## 1.3 API Routes

New file: `src/api/cloud_routes/ib_shadow.py`

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/api/ib-shadow/summary` | GET | Connection rate, contract valid rate, BP acceptance rate, total shadow count, last shadow timestamp |
| `/api/ib-shadow/log` | GET | Paginated shadow log entries (default last 50) |
| `/api/ib-shadow/health` | GET | Current IB Gateway connection status, shadow mode enabled flag |

**Summary response shape:**
```json
{
  "total_shadows": 42,
  "ib_connected_pct": 95.2,
  "ib_contract_valid_pct": 100.0,
  "ib_would_accept_pct": 88.1,
  "last_shadow_at": "2026-04-14T10:30:00",
  "errors": 3,
  "shadow_mode_enabled": true
}
```

**Log response shape:**
```json
{
  "entries": [
    {
      "shadow_id": "...",
      "created_at": "2026-04-14T10:30:00",
      "ticker": "AAPL",
      "quantity": 10,
      "entry_price": 198.50,
      "stop_price": 192.30,
      "target_price": 207.80,
      "ib_connected": 1,
      "ib_contract_valid": 1,
      "ib_buying_power": 200000.0,
      "ib_would_accept": 1,
      "ib_error": null,
      "alpaca_fill_price": 198.55
    }
  ],
  "total": 42
}
```

## 1.4 Dashboard Page: IB Shadow

**Location:** `frontend/src/pages/IBShadow.jsx`
**Nav:** System section, between "Health Score" and "Validation"
**Icon:** `GitCompare` from lucide-react (represents comparison/diff)

### Page Layout

```
┌─────────────────────────────────────────────────────┐
│ IB Shadow Mode                    [Status: ACTIVE]  │
│ Comparing IB behavior against Alpaca execution      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐│
│  │ Shadow   │ │ Gateway  │ │ Contract │ │ BP     ││
│  │ Trades   │ │ Uptime   │ │ Valid    │ │ Accept ││
│  │   42     │ │  95.2%   │ │  100%    │ │ 88.1%  ││
│  └──────────┘ └──────────┘ └──────────┘ └────────┘│
│                                                     │
│  Shadow Trade Log                                   │
│  ┌─────┬────────┬──────┬──────┬──────┬──────┬────┐ │
│  │Time │Ticker  │Qty   │Entry │IB OK │BP OK │Err │ │
│  ├─────┼────────┼──────┼──────┼──────┼──────┼────┤ │
│  │10:30│ AAPL   │  10  │198.50│  ✅  │  ✅  │    │ │
│  │10:15│ MSFT   │   5  │420.30│  ✅  │  ❌  │ BP │ │
│  │09:45│ GOOG   │   3  │175.20│  ✅  │  ✅  │    │ │
│  └─────┴────────┴──────┴──────┴──────┴──────┴────┘ │
│                                                     │
│  Error Log (if any)                                 │
│  ┌──────────────────────────────────────────────┐   │
│  │ 2026-04-14 10:15 | MSFT | BP insufficient:  │   │
│  │   Need $2,101 / Have $1,500                  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Design Tokens

Follow existing Arcis dashboard conventions:
- MetricCard component for the top row KPIs
- Table with alternating row backgrounds (`var(--arcis-bg-primary)` / `var(--arcis-bg-surface)`)
- Status badges: ✅ = `var(--arcis-success)`, ❌ = `var(--arcis-danger)`
- Shadow mode status indicator: green dot when active, gray when disabled
- Use `@tanstack/react-query` for data fetching (same pattern as all other pages)
- Tailwind utility classes only (no custom CSS)

### Empty State

When no shadow data exists (shadow mode not yet enabled or no trades yet):

```
[GitCompare icon]
IB Shadow Mode
Shadow mode logs what IB would have done for each Alpaca trade.
Enable it in settings.local.yaml: live_trading.ib.shadow_mode: true
```

## 1.5 Health Page Updates

Add to the existing System Status section in Health.jsx:

- **IB Gateway:** Connected / Disconnected / Not Configured (from `/api/ib-shadow/health`)
- **Shadow Mode:** Active / Inactive
- **Shadow Trades:** count (last 24h)

## 1.6 Risks

| Risk | Mitigation |
|------|-----------|
| No shadow data yet — page is empty on first deploy | EmptyState component with setup instructions |
| Postgres sync adds another table to sync | Incremental sync, ~1 row per trade, negligible load |
| IB shadow API errors | Standard try/except with 500 response, matches all other cloud routes |

## 1.7 Success Criteria

1. IB Shadow page renders with KPI cards and trade log
2. API routes return correct data from Render Postgres
3. Health page shows IB Gateway status
4. Nav menu includes IB Shadow link
5. Empty state displays when no shadow data exists
6. Frontend builds without errors

---

# PART 2: IMPLEMENTATION PLAN

## 2.1 File Map

| File | Action | Notes |
|------|--------|-------|
| `src/schema/registry.py` | MODIFY | Add sync flags to ib_shadow_log |
| `src/api/cloud_routes/ib_shadow.py` | CREATE | 3 API routes (~80 lines) |
| `src/api/cloud_routes/__init__.py` | MODIFY | Register new router |
| `frontend/src/pages/IBShadow.jsx` | CREATE | Dashboard page (~200 lines) |
| `frontend/src/components/Layout.jsx` | MODIFY | Add nav item |
| `frontend/src/App.jsx` | MODIFY | Add route |
| `frontend/src/api.js` | MODIFY | Add API methods |

## 2.2 API Route Pattern

Follow the exact pattern from `src/api/cloud_routes/trades.py`:

```python
def create_router(runtime, verify_auth):
    router = APIRouter()

    @router.get("/api/ib-shadow/summary", dependencies=[Depends(verify_auth)])
    def ib_shadow_summary():
        try:
            rows = runtime.query(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) as connected, "
                "SUM(CASE WHEN ib_contract_valid = 1 THEN 1 ELSE 0 END) as valid, "
                "SUM(CASE WHEN ib_would_accept = 1 THEN 1 ELSE 0 END) as accepted, "
                "SUM(CASE WHEN ib_error IS NOT NULL THEN 1 ELSE 0 END) as errors, "
                "MAX(created_at) as last_at "
                "FROM ib_shadow_log"
            )
            # ... build response
        except Exception as exc:
            runtime.logger.error("[API] ib-shadow summary failed: %s", exc)
            return {"total_shadows": 0, "error": str(exc)}
```

## 2.3 Frontend Component Pattern

Follow LiveLedger.jsx patterns:
- `useQuery` with `queryKey: ['ib-shadow-summary']`
- `MetricCard` components for KPIs
- Table with `TickerLogo`, status badges, timestamps
- `LoadingSpinner` and `EmptyState` for loading/empty states
- 60-second refetch interval

---

# PART 3: SPRINT PROMPT

> **Branch:** `feat/ib-shadow-dashboard`
> **Depends on:** `feat/ib-tests-shadow` must be merged first
> **Priority:** MEDIUM
> **Estimated CC time:** 3–4 hours
>
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b feat/ib-shadow-dashboard
> cd frontend && npm run build && cd ..
> ```

---

## Task 1: Update ib_shadow_log schema for Postgres sync

**File:** `src/schema/registry.py`

Find the `ib_shadow_log` TableDef and add sync configuration:

```python
sync_to_postgres=True,
sync_mode="incremental",
sync_time_column="created_at",
sync_pk="shadow_id",
```

**Commit:** `schema: enable Postgres sync for ib_shadow_log`

---

## Task 2: Create IB Shadow API routes

**File:** Create `src/api/cloud_routes/ib_shadow.py` (~80 lines)

Three endpoints: `/api/ib-shadow/summary`, `/api/ib-shadow/log`, `/api/ib-shadow/health`.

Follow the exact `create_router(runtime, verify_auth)` pattern from `trades.py`. Use `runtime.query()` and `runtime.query_one()` for Postgres access. Wrap every handler in try/except.

`/api/ib-shadow/health` should also check the config for `ib.shadow_mode`:
```python
@router.get("/api/ib-shadow/health", dependencies=[Depends(verify_auth)])
def ib_shadow_health():
    config = runtime.config or {}
    ib_cfg = config.get("live_trading", {}).get("ib", {})
    shadow_enabled = ib_cfg.get("shadow_mode", False)
    return {
        "shadow_mode_enabled": shadow_enabled,
        "broker": config.get("live_trading", {}).get("broker", "alpaca"),
    }
```

**Register the router** in `src/api/cloud_routes/__init__.py`:
```python
from src.api.cloud_routes.ib_shadow import create_router as ib_shadow_router
# ... in the registration function:
app.include_router(ib_shadow_router(runtime, verify_auth))
```

**Commit:** `feat(api): IB shadow routes — summary, log, health`

---

## Task 3: Add frontend API methods

**File:** `frontend/src/api.js`

Add to the API object:
```javascript
// IB Shadow
getIBShadowSummary: () => fetchApi('/ib-shadow/summary'),
getIBShadowLog: (limit = 50) => fetchApi(`/ib-shadow/log?limit=${limit}`),
getIBShadowHealth: () => fetchApi('/ib-shadow/health'),
```

**Commit:** `feat(api.js): add IB shadow API methods`

---

## Task 4: Create IB Shadow dashboard page

**File:** Create `frontend/src/pages/IBShadow.jsx` (~200 lines)

Follow the LiveLedger.jsx pattern:
- Import `useQuery` from `@tanstack/react-query`
- Import `MetricCard`, `LoadingSpinner`, `EmptyState` from components
- Import `GitCompare` from `lucide-react`
- Use `api.getIBShadowSummary()` and `api.getIBShadowLog()` queries
- 60-second refetch interval

**Top row:** 4 MetricCards:
1. Shadow Trades (total count)
2. Gateway Uptime (ib_connected_pct, green if >90%, yellow if >70%, red below)
3. Contract Valid (ib_contract_valid_pct, should be ~100%)
4. BP Acceptance (ib_would_accept_pct)

**Main table:** Shadow trade log with columns:
- Time (formatted created_at)
- Ticker (with TickerLogo)
- Qty
- Entry Price
- IB Connected (✅/❌ badge)
- Contract Valid (✅/❌ badge)
- BP Accept (✅/❌ badge)
- Error (truncated, expandable)

**Empty state:** When no shadow data, show setup instructions.

**Commit:** `feat(dashboard): IB Shadow page — comparison analytics for shadow mode`

---

## Task 5: Add navigation and routing

**File:** `frontend/src/components/Layout.jsx`

Add to the System nav section, after Health Score:
```javascript
{ to: '/ib-shadow', icon: GitCompare, label: 'IB Shadow' },
```

Import `GitCompare` from lucide-react at the top.

**File:** `frontend/src/App.jsx`

Add route:
```javascript
import IBShadow from './pages/IBShadow'
// In routes:
<Route path="/ib-shadow" element={<ErrorBoundary><IBShadow /></ErrorBoundary>} />
```

**Commit:** `feat(nav): add IB Shadow to dashboard navigation`

---

## Task 6: Build verification

```bash
cd frontend && npm run build && cd ..
```

Must pass. If it fails, fix JSX syntax before committing.

**Commit:** (no commit — verification only)

---

## Task 7: Documentation

**Files:** `CHANGELOG.md`, `MASTER.md`

**Commit:** `docs: IB shadow dashboard page + API routes`

**Push:**
```bash
git push origin feat/ib-shadow-dashboard
```

---

## Verification Checklist

```bash
# Frontend builds
cd frontend && npm run build && cd ..

# API routes importable
python -c "from src.api.cloud_routes.ib_shadow import create_router; print('✓')"

# Schema has sync flags
grep -A5 "ib_shadow_log" src/schema/registry.py | grep "sync_to_postgres"

# No Python test regressions
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# Nav has new item
grep "ib-shadow" frontend/src/components/Layout.jsx
grep "ib-shadow" frontend/src/App.jsx
```

---

## Ralph Loop Findings

**Spec Pass 1:** Initially forgot to register the router in `__init__.py` — routes would exist but never mount. Added explicit registration step.

**Spec Pass 2:** The `/api/ib-shadow/health` endpoint needs access to runtime.config to check if shadow_mode is enabled. Not all cloud routes access config — verified that `runtime.config` is available (it is — set during startup).

**Spec Pass 3:** The Health.jsx page update was scoped initially but adds complexity to an already complex page. Deferred to a separate micro-PR — the IB Shadow page itself shows all the health info.

**Implementation Pass 1:** The API route file must follow the `create_router(runtime, verify_auth)` factory pattern exactly — CC sometimes creates standalone FastAPI routers without the runtime injection.

**Implementation Pass 2:** The `ib_shadow_log` query uses `SUM(CASE WHEN ... THEN 1 ELSE 0 END)` for percentage calculations. Postgres and SQLite both support this syntax — no compatibility issue.

**Implementation Pass 3:** Added `limit` parameter to the log endpoint to prevent loading thousands of rows. Default 50, matches the pattern from other paginated endpoints.

**Sprint Pass 1:** Task ordering matters — schema sync (Task 1) must come before API routes (Task 2) because the route queries Postgres which needs the table.

**Sprint Pass 2:** The `GitCompare` icon import needs to be verified — checked lucide-react 1.8.0 (just merged) and `GitCompare` exists.

**Sprint Pass 3:** EmptyState component must include actionable setup instructions, not just "no data." Users seeing an empty page with no guidance is a bad UX — added specific yaml config instruction.

---

# APPENDIX: IB Trading Logic Gap Analysis

## What's Currently Implemented

The `ib_broker.py` adapter (271 lines) is a thin compatibility wrapper. It translates generic `BrokerAdapter` method calls into ib_async API calls:

| BrokerAdapter Method | IB Implementation | Status |
|---------------------|-------------------|--------|
| `place_bracket_order` | `bracketOrder()` → 3 OCA-linked orders, GTC | ✅ Correct |
| `place_market_order` | `MarketOrder()`, GTC | ✅ Correct |
| `place_exit` | Looks up position, sells all | ✅ Correct |
| `cancel_order` | Searches `openTrades()`, cancels match | ✅ Correct |
| `get_order_status` | Searches `trades()` by orderId | ✅ Correct |
| `get_position` | Searches `positions()` by symbol | ✅ Correct |
| `get_all_positions` | Returns all `positions()` | ✅ Correct |
| `get_account` | Parses `accountSummary()` tags | ✅ Correct |
| `get_current_price` | Snapshot `reqMktData()` | ✅ Correct |
| `is_connected` | Checks `_ib.isConnected()` | ✅ Correct |

**For shadow mode and initial paper trading, this is sufficient.**

## What's NOT Built (Production IB Gaps)

These must be addressed before IB live trading (Phase 2+, after 60+ trades):

| Gap | Risk | When to Fix |
|-----|------|-------------|
| **Gateway daily reset (11:45 PM ET)** | Connection drops, open orders may be affected | Before IB paper trades are live (not shadow) |
| **Event-driven fills** | Current `sleep(2)` may miss fast fills or timeout on slow fills | Before IB paper trades |
| **Partial fills** | IB can partially fill orders; code assumes full fills | Before IB paper trades |
| **IB error codes** | Numeric error codes (110, 201, etc.) need specific handling | Before IB paper trades |
| **Order status mapping** | IB has PreSubmitted, Submitted, Filled, Cancelled, Inactive, ApiCancelled, etc. | Before IB paper trades |
| **Market data line management** | 100-line limit; need to track active subscriptions | Before IB paper trades |
| **Extended hours behavior** | IB brackets may trigger during pre/after-market | Before IB paper trades |
| **Margin calculation differences** | IB paper vs live vs Alpaca have different margin rules | Before IB live trades |
| **Adaptive order types** | IB supports TWAP, VWAP, midpoint peg — unused | Phase 3+ (optimization) |
| **IB Scanner** | Could replace yfinance for universe scanning — unused | Phase 3+ (optimization) |
| **IB Historical Data** | Could replace yfinance for stress tests — unused | Phase 3+ (data quality) |

**For both strategies (pullback + mean reversion), the current bracket/market order implementation is functionally correct.** The gaps are about resilience and edge cases, not core trading logic. The shadow mode sprint validates the basic flow; the gaps above get their own sprint when we activate IB paper trading (not shadow).

## Recommended Sequence

1. **Now:** IB Tests + Shadow Mode sprint (backend) — validates code correctness
2. **Next:** IB Shadow Dashboard sprint (frontend) — makes shadow data visible
3. **Week 2:** Start IB Gateway, enable shadow mode alongside Alpaca paper
4. **Week 3-4:** Accumulate shadow comparison data, verify connectivity patterns
5. **Month 2:** Write IB Production Hardening sprint (Gateway reset, partial fills, error codes)
6. **Month 2:** Activate IB paper trading (not shadow — real orders)
7. **Month 3+:** IB live trading after 30-day stability gate passes
