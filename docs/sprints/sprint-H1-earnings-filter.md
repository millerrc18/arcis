# Sprint H1: Earnings Filter — Skip Trades Within Earnings Window

**Authority:** SD#33 earnings gap risk mitigation
**Effort:** 4-6 hours CC time
**Branch:** `feat/earnings-filter`
**Tag on merge:** `v0.21.0`
**Priority:** HIGH — approved for execution in parallel with D1/D2/D3 diagnostics
**Rationale:** Gap risk from earnings surprises is independent of the alpha-vs-beta question. Even if Arcis turns out to be SPY beta, eliminating earnings gap losses improves the product.
**Ralph-loop status:** First draft

---

## Goal

Prevent Arcis from entering any new pullback trade when the ticker is within 7 trading days of a scheduled earnings announcement. The pullback strategy assumes mean-reversion over 3-8 day holds; an earnings surprise can produce a 5-15% gap that overwhelms the strategy's normal bracket risk. Filtering earnings-adjacent trades removes the primary source of fat-tail losses.

After this sprint:
- Every new recommendation checks the earnings calendar before being marked as tradeable
- Trades within 7 trading days of earnings are rejected at the recommendation layer (never reach execution)
- The `recommendations.earnings_adjacent` flag is populated (currently mostly unused)
- Dashboard shows earnings-adjacent rejection count in the daily scan summary

---

## Background Context for CC

**Why this matters:**
- Current `shadow_trades.earnings_adjacent` column exists but is rarely set
- Forensic analysis showed 62 of 78 trades exit as reconciled_stale — some of these may be trades that never resolved because earnings hit mid-hold and the strategy couldn't recover
- Gap risk cannot be managed by vol-targeting, tighter stops, or any exit optimization. The only mitigation is avoiding the event entirely

**Data sources available:**
- Finnhub earnings calendar (rate-limited but sufficient for 102 tickers)
- FMP (Financial Modeling Prep) earnings calendar
- yfinance `Ticker.earnings_dates` (fallback, less reliable)

**Full authority:** See `docs/research/Alternative_Data_Signals_for_Large-Cap_Short-Horizon_Trading__A_Cost-Benefit_Analysis_for_the_Halcyon_Lab_Stack.md` for the research foundation.

---

## Pre-Flight Checks

1. **Verify earnings data availability:**
   ```bash
   python -c "from src.data.finnhub_client import get_earnings_calendar; print(get_earnings_calendar('AAPL', days_ahead=14))"
   ```
   Expected: upcoming earnings date for AAPL. If the client doesn't exist, this sprint includes building it.

2. **Check current state of earnings_adjacent column:**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); [print(r) for r in db.execute('SELECT earnings_adjacent, COUNT(*) FROM shadow_trades GROUP BY earnings_adjacent').fetchall()]"
   ```

3. **Check recommendations table for earnings fields:**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); print([r[1] for r in db.execute('PRAGMA table_info(recommendations)').fetchall() if 'earning' in r[1].lower()])"
   ```

4. **Create feature branch:**
   ```bash
   git checkout -b feat/earnings-filter
   ```

---

## Task List (max 10 tasks)

### Task 1 — Earnings calendar client (if not already robust)

**File:** `src/data/earnings_calendar.py` (new or enhance existing)

```python
"""Earnings calendar fetcher with caching and multi-source fallback.

Authority: SD#33 earnings gap risk mitigation.

Primary source: Finnhub (daily rate-limited, free tier sufficient for 102 tickers)
Fallback: FMP (if Finnhub fails)
Last resort: yfinance (least reliable for forward-looking dates)

Cache: Daily refresh of full S&P 100 earnings calendar for next 90 days.
"""

from __future__ import annotations
import datetime as dt
import logging
from pathlib import Path
from typing import Optional
import json

logger = logging.getLogger(__name__)

CACHE_PATH = Path("data/cache/earnings_calendar.json")
CACHE_TTL_HOURS = 24


def refresh_earnings_cache(tickers: list[str]) -> dict[str, list[str]]:
    """Fetch next 90 days of earnings for all tickers. Persist to cache.
    
    Returns: {ticker: [ISO date strings]} for any tickers with upcoming earnings.
    """
    # Try Finnhub first
    try:
        calendar = _fetch_finnhub_bulk(tickers, days_ahead=90)
        if calendar:
            _write_cache(calendar)
            return calendar
    except Exception as exc:
        logger.warning("[EARNINGS] Finnhub bulk fetch failed: %s", exc)
    
    # Fallback: FMP
    try:
        calendar = _fetch_fmp_bulk(tickers, days_ahead=90)
        if calendar:
            _write_cache(calendar)
            return calendar
    except Exception as exc:
        logger.warning("[EARNINGS] FMP bulk fetch failed: %s", exc)
    
    # Last resort: yfinance per-ticker (slow)
    logger.warning("[EARNINGS] Falling back to yfinance per-ticker")
    calendar = {}
    for ticker in tickers:
        try:
            dates = _fetch_yfinance_single(ticker, days_ahead=90)
            if dates:
                calendar[ticker] = dates
        except Exception as exc:
            logger.debug("[EARNINGS] yfinance failed for %s: %s", ticker, exc)
    _write_cache(calendar)
    return calendar


def is_earnings_adjacent(ticker: str, reference_date: dt.date,
                         days_before: int = 7, days_after: int = 1) -> bool:
    """Check whether ticker has an earnings event within the window around reference_date.
    
    Default window: 7 trading days before, 1 trading day after. This catches:
    - Pre-announcement risk (run-up / drift)
    - Day-of announcement gap
    - Post-announcement reaction (first day)
    
    Returns True if ANY scheduled earnings falls in the window.
    """
    calendar = _load_cache()
    if not calendar:
        logger.warning("[EARNINGS] Cache empty; cannot evaluate %s", ticker)
        return False  # fail-open: don't block trading if we can't check
    
    dates = calendar.get(ticker, [])
    if not dates:
        return False  # no known upcoming earnings
    
    # Compute window in calendar days (approximation of trading days)
    window_start = reference_date - dt.timedelta(days=int(days_before * 1.5))  # calendar buffer
    window_end = reference_date + dt.timedelta(days=int(days_after * 1.5))
    
    for iso_date in dates:
        try:
            earnings_date = dt.date.fromisoformat(iso_date)
            if window_start <= earnings_date <= window_end:
                return True
        except ValueError:
            continue
    return False


# Helper implementations
def _load_cache() -> dict[str, list[str]]:
    if not CACHE_PATH.exists():
        return {}
    # Check TTL
    age_hours = (dt.datetime.now().timestamp() - CACHE_PATH.stat().st_mtime) / 3600
    if age_hours > CACHE_TTL_HOURS:
        logger.info("[EARNINGS] Cache stale (%.1fh); returning empty", age_hours)
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception as exc:
        logger.warning("[EARNINGS] Cache read failed: %s", exc)
        return {}


def _write_cache(calendar: dict[str, list[str]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(calendar, indent=2))


def _fetch_finnhub_bulk(tickers, days_ahead):
    # Implementation uses existing Finnhub client if available
    # Returns {ticker: [iso_date, ...]} or {} on failure
    raise NotImplementedError  # CC implements based on existing Finnhub client


def _fetch_fmp_bulk(tickers, days_ahead):
    raise NotImplementedError  # CC implements based on existing FMP client


def _fetch_yfinance_single(ticker, days_ahead):
    import yfinance as yf
    t = yf.Ticker(ticker)
    df = t.earnings_dates
    if df is None or df.empty:
        return []
    cutoff = dt.datetime.now() + dt.timedelta(days=days_ahead)
    upcoming = df[df.index <= cutoff]
    return [idx.date().isoformat() for idx in upcoming.index if idx >= dt.datetime.now()]
```

**Constraint:** File size ≤ 200 lines. If any method exceeds 50 lines, refactor.

### Task 2 — Scheduler task: daily earnings cache refresh

**File:** `src/scheduler/watch.py` (or wherever pre-market tasks live)

Add a daily task at 4:00 AM ET (before scan cycle):

```python
def _refresh_earnings_cache(ctx):
    """Daily pre-market: refresh earnings calendar for S&P 100."""
    try:
        from src.data.earnings_calendar import refresh_earnings_cache
        tickers = ctx.universe.tickers  # S&P 100 list
        calendar = refresh_earnings_cache(tickers)
        ctx.logger.info("[EARNINGS] Refreshed calendar: %d tickers with upcoming earnings",
                       len([k for k, v in calendar.items() if v]))
    except Exception as exc:
        ctx.logger.error("[EARNINGS] Cache refresh failed: %s", exc)
        # Do not fail the scan cycle; fall back to stale cache
```

**Schedule:** Daily at 4:00 AM ET, before the first scan.

### Task 3 — Ranker integration: reject earnings-adjacent setups

**File:** `src/ranker/deterministic_ranker.py` (or equivalent — where setups become recommendations)

At the point where a setup is about to be promoted to a recommendation, add the earnings check:

```python
from src.data.earnings_calendar import is_earnings_adjacent

# ... existing ranker logic that builds the candidate ...

if is_earnings_adjacent(candidate.ticker, today):
    candidate.rejected = True
    candidate.rejection_reason = 'earnings_adjacent'
    # Still log the recommendation (for attribution) but mark as not executable
    candidate.tradeable = False
```

**Constraint:** The recommendation is still written to the DB (so attribution can track what was rejected and why), but `tradeable=False` prevents execution.

### Task 4 — Executor guardrail: double-check at execution time

**File:** `src/shadow_trading/executor.py`

Add a belt-and-suspenders check right before opening a position:

```python
from src.data.earnings_calendar import is_earnings_adjacent
import datetime as dt

# ... before placing bracket order ...

if is_earnings_adjacent(ticker, dt.date.today()):
    logger.warning("[EXECUTOR] Skipping %s: earnings-adjacent (double-check)", ticker)
    # Mark the recommendation as skipped, don't open position
    return _record_rejection(recommendation_id, 'earnings_adjacent_executor_guard')
```

This prevents any race condition where the ranker cleared the trade but earnings data updated before execution.

### Task 5 — Position monitoring: flag existing positions approaching earnings

**File:** `src/shadow_trading/executor.py` (monitoring section) or `src/scheduler/watch.py`

For open positions: if any existing hold is going to cross its ticker's earnings date within the next 2 trading days, log a warning. This is informational only — don't close positions automatically (that would conflict with the bracket logic).

```python
# Daily check on open positions
for position in open_positions:
    if is_earnings_adjacent(position.ticker, today, days_before=2, days_after=0):
        logger.warning("[EARNINGS] Open position %s approaches earnings within 2 days",
                      position.ticker)
        # Emit a metric / dashboard alert
```

**Constraint:** Do not auto-close. Just alert. Closing policy during earnings is a separate decision (SD candidate for future).

### Task 6 — Populate `earnings_adjacent` column for historical trades

**File:** `scripts/backfill_earnings_adjacent.py` (new)

For all existing closed trades:
1. Check whether their entry date was within 7 days of the ticker's nearest historical earnings
2. Update the `shadow_trades.earnings_adjacent` column

This requires HISTORICAL earnings dates (not just future). Use:
- yfinance `Ticker.earnings_dates` — historical earnings back a few years
- FMP historical earnings endpoint

**Constraint:** If historical data isn't available for a ticker, leave the column NULL (don't guess).

### Task 7 — Dashboard: earnings rejection count

**File:** `frontend/src/pages/Dashboard.jsx`

Add a small metric card to the daily scan summary:

```jsx
<div className="arcis-card">
  <div className="text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Earnings-Adjacent Rejected</div>
  <div className="text-2xl font-medium" style={MONO}>{earningsRejectedToday}</div>
  <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
    Today's scan
  </div>
</div>
```

And a 30-day sparkline showing the daily rejection count — useful to see whether we're catching a handful per day (normal) or suddenly a lot (earnings season).

### Task 8 — Regression tests

**File:** `tests/data/test_earnings_calendar.py` (new)

Minimum tests:
1. `test_is_earnings_adjacent_true_when_earnings_in_window`
2. `test_is_earnings_adjacent_false_when_no_earnings`
3. `test_is_earnings_adjacent_fail_open_on_empty_cache` — doesn't block trading if we can't check
4. `test_cache_ttl_expired_returns_empty`
5. `test_ranker_rejects_earnings_adjacent_setup` — integration
6. `test_executor_double_checks_earnings_adjacent` — integration

### Task 9 — Metrics + alerting

**File:** `src/monitoring/metrics.py` (or wherever)

Add two metrics:
- `arcis_earnings_rejections_total` — counter, labels by ticker
- `arcis_open_position_approaching_earnings` — gauge, labels by ticker + days_to_earnings

If Grafana is wired (SD#40), add a dashboard panel for these. Alert if any open position is within 1 trading day of earnings and no exit plan (should be rare post-filter).

### Task 10 — Documentation updates

**Files:**
- `CHANGELOG.md` — v0.21.0 entry
- `RELEASES.md`
- `MASTER.md` — update SD#33 status to "implemented"
- `docs/strategy-decisions.md` — mark SD#33 as complete
- `README.md` — update version badge

**CHANGELOG entry:**
```markdown
## v0.21.0 (TBD)

### Added
- **Earnings filter (SD#33).** Trades within 7 trading days of earnings are
  rejected at the ranker layer with rejection_reason='earnings_adjacent'.
  Executor double-checks at entry time to prevent race conditions.
- Daily pre-market earnings calendar refresh for S&P 100 (Finnhub primary,
  FMP fallback, yfinance last resort).
- Dashboard panel: earnings-adjacent rejection count (today + 30d sparkline).
- Open position monitoring: warning log if any open hold crosses earnings
  within 2 trading days.
- Backfill: shadow_trades.earnings_adjacent populated for historical trades
  where earnings dates are available.

### Rationale
Earnings gap risk cannot be managed by vol-targeting, stops, or exit
optimization. The only mitigation is avoiding the event. Per forensic
analysis, gap losses are a plausible contributor to the reconciled_stale
rate (62 of 78 trades).
```

---

## Success Criteria

1. Daily earnings cache refresh runs successfully pre-market
2. Ranker rejects earnings-adjacent setups with logged reason
3. Executor double-checks at execution time
4. `shadow_trades.earnings_adjacent` backfilled for historical trades
5. Dashboard shows rejection count
6. 6 new tests pass
7. No regressions
8. Frontend builds
9. Open 2-week observation: no trades enter earnings-adjacent positions

---

## Commit Messages

```
feat(data): earnings calendar client with Finnhub/FMP/yfinance fallback
feat(scheduler): daily pre-market earnings cache refresh
feat(ranker): reject earnings-adjacent setups (SD#33)
feat(executor): double-check earnings adjacency at entry time
feat(monitoring): warn on open positions approaching earnings
feat(scripts): backfill earnings_adjacent for historical trades
feat(frontend): dashboard shows earnings rejection count
test: earnings calendar + ranker/executor integration
docs: SD#33 earnings filter complete
```

---

## Out-of-Scope

- Closing existing positions that hit earnings mid-hold (requires separate SD)
- Post-earnings reentry logic (separate design)
- Sector-wide earnings season throttling (different SD)
- Options data collection around earnings (Phase 3+)

---

## Ralph-Loop Review Questions

1. **Fail-open or fail-closed on cache miss?** Fail-open (trade as normal) is the less-destructive default. Documented.
2. **Why not use options IV spike as earnings proxy?** More complex, less reliable. Calendar is the ground truth.
3. **What about companies without regular earnings (IPOs, REITs)?** If no future earnings date in cache, no filter applied. Fine.
4. **Does this affect Phase 1 OOS validation?** Yes — earnings filter reduces variance which improves raw AND excess Sharpe. Worth it; earnings risk isn't what we want to learn about.

---

*Ready for 3× Ralph-loop review before CC execution.*
