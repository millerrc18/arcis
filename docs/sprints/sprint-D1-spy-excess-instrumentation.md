# Sprint D1: SPY-Matched Excess Return Instrumentation

**Authority:** SD#41 REVISED `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
**Effort:** 1 weekend (8-10 hours CC time including Ralph-loop)
**Branch:** `feat/spy-excess-instrumentation`
**Tag on merge:** `v0.19.0`
**Priority:** CRITICAL — blocks all Phase 1 optimization work
**Ralph-loop status:** First draft, needs 3× review before CC execution

---

## Goal

Make every metric in Arcis answer the question "is this alpha or is this SPY beta?" Currently we cannot. After this sprint every closed trade will have an SPY-matched excess return logged, backfilled for all 78 historical trades, and the dashboard will show **excess-return Sharpe as the primary metric** with raw Sharpe demoted to secondary.

This is the single most important instrumentation change in Arcis's history. The forensic analysis revealed that per-trade Sharpe 3.38 is mostly SPY beta during a bull run (excess vs SPY is +0.039% with t=0.098). We cannot claim alpha without this instrumentation. We cannot pass the redefined IB gate without this instrumentation. Investor materials cannot cite Sharpe without this instrumentation.

---

## Background Context for CC

- **Dataset snapshot:** 78 closed trades, date range 2026-03-24 to 2026-04-13, ~22 trading days
- **Current metric:** Per-trade Sharpe 3.38, 95% CI [2.80, 3.96] — looks great in isolation
- **Hidden problem:** SPY returned ~12% in those 22 days. Arcis is 60-80% invested in SPY-correlated names. The per-trade Sharpe reflects efficient SPY beta capture, not alpha.
- **Forensic measurement:** Mean excess vs SPY = +0.039% per trade, t=0.098, hit rate beating SPY = 56%. Arcis is statistically indistinguishable from a passive SPY overlay with matched exposure.
- **Redefined IB gate:** Excess-return Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (replaces "raw Sharpe ≥ 1.0" which is trivially passed by beta)

Full context: `docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf` Section 6.

---

## Pre-Flight Checks

1. **Verify yfinance is available and functional:**
   ```bash
   python -c "import yfinance as yf; print(yf.Ticker('SPY').history(period='5d').tail())"
   ```
   Expected: 5 days of SPY OHLC data prints without error.

2. **Verify current schema:**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); print([r[1] for r in db.execute('PRAGMA table_info(shadow_trades)').fetchall()])"
   ```
   Expected: current column list. Should NOT already contain `spy_return_over_hold`, `excess_return`, or `realized_sector`.

3. **Verify trade count baseline:**
   ```bash
   python -c "from src.storage.database import get_db; db=get_db(); n=db.execute('SELECT COUNT(*) FROM shadow_trades WHERE actual_exit_time IS NOT NULL').fetchone()[0]; print(f'Closed trades: {n}')"
   ```
   Expected: 78 or higher (may have grown since forensic report).

4. **Verify clean working tree:**
   ```bash
   git status
   git branch --show-current  # should be main
   git checkout -b feat/spy-excess-instrumentation
   ```

---

## Task List (max 10 tasks)

### Task 1 — Schema migration: add three columns to `shadow_trades`

**File:** `src/schema/registry.py` (or wherever `shadow_trades` ColumnDefs live — CC should verify)

Add after the existing MAE/MFE columns:

```python
ColumnDef("spy_return_over_hold", "REAL",
    description="SPY total return (close-to-close) over the exact entry-to-exit date range. "
                "Used for alpha vs beta attribution. See SD#41 REVISED."),
ColumnDef("excess_return", "REAL",
    description="pnl_pct - spy_return_over_hold. This is the primary alpha measurement. "
                "Positive = beat SPY; negative = underperformed SPY over same period."),
ColumnDef("realized_sector", "TEXT",
    description="GICS sector (Technology, Healthcare, Financials, etc.) from manual lookup table. "
                "Temporary until sector_context classifier is repaired per D3."),
```

**Schema migration:** use the existing `scripts/schema_apply.py` or equivalent migration pattern. Ensure idempotent — running twice is safe.

**Constraint:** Do not touch any other columns. This is purely additive.

---

### Task 2 — Build GICS sector lookup CSV

**File:** `data/sp100-gics-lookup.csv` (new file)

Two-column CSV: `ticker,gics_sector`

The 11 GICS sectors: Technology, Health Care, Financials, Consumer Discretionary, Consumer Staples, Industrials, Energy, Utilities, Real Estate, Materials, Communication Services.

CC should:
1. Query distinct tickers from `shadow_trades` + `recommendations`:
   ```sql
   SELECT DISTINCT ticker FROM shadow_trades
   UNION
   SELECT DISTINCT ticker FROM recommendations
   ```
2. For each ticker, assign GICS sector. Canonical source: Wikipedia S&P 100 component list by sector, or use yfinance's `.info.get('sector')` as cross-check.
3. Produce ~102 rows. Commit the CSV.

**Validation:** Every ticker in `shadow_trades` and `recommendations` must have a row. Unknown tickers default to `Unknown` with a TODO comment in the code.

---

### Task 3 — Implement SPY return calculator utility

**File:** `src/analytics/spy_benchmark.py` (new file, ~80 lines max)

```python
"""SPY-matched excess return calculations.

Authority: SD#41 REVISED — converts every metric from raw-Sharpe to
excess-Sharpe to distinguish alpha from SPY beta.
"""

from __future__ import annotations
import logging
import datetime as dt
from typing import Optional
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# Cache SPY history for the session to avoid repeated API calls
_spy_history_cache: Optional[pd.DataFrame] = None


def get_spy_history(start: str, end: str) -> pd.DataFrame:
    """Fetch SPY daily closes. Cached per session."""
    global _spy_history_cache
    if _spy_history_cache is None or _spy_history_cache.index.min() > pd.Timestamp(start):
        _spy_history_cache = yf.Ticker("SPY").history(
            start=start, end=end, auto_adjust=True
        )
    return _spy_history_cache


def spy_return_over_range(entry_iso: str, exit_iso: str) -> Optional[float]:
    """Return SPY total return (as fraction, not %) from entry close to exit close.
    
    entry_iso / exit_iso: ISO 8601 datetime strings.
    Returns None if SPY data unavailable for either date.
    """
    try:
        entry_date = dt.datetime.fromisoformat(entry_iso).date()
        exit_date = dt.datetime.fromisoformat(exit_iso).date()
        # Fetch a window that includes both dates (with buffer for non-trading days)
        start = (entry_date - dt.timedelta(days=5)).isoformat()
        end = (exit_date + dt.timedelta(days=5)).isoformat()
        hist = yf.Ticker("SPY").history(start=start, end=end, auto_adjust=True)
        if hist.empty:
            return None
        # Find entry close (first trading day at or after entry_date)
        entry_close = hist.loc[hist.index.date >= entry_date, 'Close'].iloc[0]
        exit_close = hist.loc[hist.index.date >= exit_date, 'Close'].iloc[0]
        return float((exit_close - entry_close) / entry_close)
    except (IndexError, KeyError, ValueError) as exc:
        logger.warning("[SPY_BENCH] Could not compute SPY return %s->%s: %s",
                      entry_iso, exit_iso, exc)
        return None


def excess_return(pnl_pct: float, spy_return: Optional[float]) -> Optional[float]:
    """Excess return = trade pnl% - SPY return over same period (both as percentages).
    
    spy_return is a fraction (0.01 = 1%). pnl_pct is already a percentage.
    """
    if spy_return is None:
        return None
    return pnl_pct - (spy_return * 100.0)
```

**Tests:** `tests/analytics/test_spy_benchmark.py` with at least 3 test cases:
1. Known date range (e.g., 2026-03-24 entry, 2026-03-26 exit) — verify SPY return is computed
2. Invalid/future date — verify None is returned, not exception
3. Same-day exit — verify returns 0 or near-0

---

### Task 4 — Backfill script for existing 78 trades

**File:** `scripts/backfill_spy_excess.py` (new file, ~60 lines max)

```python
"""Backfill spy_return_over_hold, excess_return, realized_sector
for all existing closed trades.

Usage: python scripts/backfill_spy_excess.py [--dry-run]

Idempotent: safe to run multiple times. Skips rows that already have
values unless --force is passed.
"""

import argparse
import csv
import logging
from pathlib import Path
from src.storage.database import get_db
from src.analytics.spy_benchmark import spy_return_over_range, excess_return

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def load_sector_lookup() -> dict[str, str]:
    path = Path("data/sp100-gics-lookup.csv")
    out = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            out[row['ticker']] = row['gics_sector']
    return out


def backfill(dry_run: bool = False, force: bool = False):
    db = get_db()
    sectors = load_sector_lookup()
    
    query = """
        SELECT trade_id, ticker, actual_entry_time, actual_exit_time, pnl_pct,
               spy_return_over_hold, excess_return, realized_sector
        FROM shadow_trades
        WHERE actual_exit_time IS NOT NULL AND pnl_pct IS NOT NULL
    """
    rows = db.execute(query).fetchall()
    logger.info("Backfill candidates: %d closed trades", len(rows))
    
    updated = 0
    skipped_existing = 0
    skipped_no_spy = 0
    unknown_sectors = []
    
    for row in rows:
        trade_id, ticker, entry_t, exit_t, pnl_pct = row[:5]
        existing_spy, existing_excess, existing_sector = row[5:]
        
        if not force and existing_spy is not None and existing_excess is not None:
            skipped_existing += 1
            continue
        
        spy_ret = spy_return_over_range(entry_t, exit_t)
        if spy_ret is None:
            skipped_no_spy += 1
            continue
        
        excess = excess_return(pnl_pct, spy_ret)
        sector = sectors.get(ticker, 'Unknown')
        if sector == 'Unknown':
            unknown_sectors.append(ticker)
        
        if dry_run:
            logger.info("[DRY] %s pnl=%.2f%% spy=%.2f%% excess=%.2f%% sector=%s",
                       ticker, pnl_pct, spy_ret * 100, excess, sector)
        else:
            db.execute("""
                UPDATE shadow_trades
                SET spy_return_over_hold = ?, excess_return = ?, realized_sector = ?
                WHERE trade_id = ?
            """, (spy_ret, excess, sector, trade_id))
            db.commit()
            updated += 1
    
    logger.info("Updated: %d | Skipped (existing): %d | Skipped (no SPY): %d",
               updated, skipped_existing, skipped_no_spy)
    if unknown_sectors:
        logger.warning("Unknown sectors (fix sp100-gics-lookup.csv): %s", unknown_sectors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, force=args.force)
```

**Validation:**
1. Run with `--dry-run` first. Verify it would update ~78 rows.
2. Run without flags. Verify updates complete.
3. Run again. Verify all 78 are skipped_existing (idempotency confirmed).

---

### Task 5 — Hook into executor: populate columns on every new exit

**File:** `src/shadow_trading/executor.py` (where exits are recorded — CC should grep for where `pnl_pct` and `pnl_dollars` are computed on exit)

At the point where exit data is written, add:

```python
from src.analytics.spy_benchmark import spy_return_over_range, excess_return

# ... existing exit logic that computes pnl_pct ...

spy_ret = spy_return_over_range(entry_time_iso, exit_time_iso)
excess = excess_return(pnl_pct, spy_ret)
sector = _get_sector(ticker)  # uses the sector lookup CSV

# ... when writing to shadow_trades, include the new columns ...
```

Add a helper `_get_sector(ticker)` that lazy-loads the GICS lookup once per process.

**Constraint:** If SPY fetch fails (network error), write NULL for spy_return_over_hold and excess_return. Do not fail the exit — the trade is what matters; the instrumentation is additive.

---

### Task 6 — Backend API: expose excess-Sharpe alongside raw Sharpe

**File:** `src/api/cloud_routes/trades.py` (GET /api/shadow/closed)

In the response payload, ensure the new columns are included:
- `spy_return_over_hold`
- `excess_return`
- `realized_sector`

Add a new aggregate endpoint: `GET /api/shadow/sharpe-attribution` that returns:

```json
{
  "n_trades": 78,
  "raw_sharpe": 3.38,
  "raw_sharpe_ci_low": 2.80,
  "raw_sharpe_ci_high": 3.96,
  "excess_sharpe": 0.139,
  "excess_sharpe_ci_low": -0.08,
  "excess_sharpe_ci_high": 0.35,
  "excess_t_stat": 0.098,
  "hit_rate_vs_spy": 56.0,
  "mean_excess_pct": 0.039,
  "trades_with_spy_data": 75,
  "trades_missing_spy_data": 3,
  "interpretation": "alpha_not_demonstrated"  
}
```

Interpretation enum:
- `"alpha_not_demonstrated"` if excess_t < 1.0
- `"alpha_suggestive"` if 1.0 ≤ excess_t < 2.0
- `"alpha_significant"` if excess_t ≥ 2.0

**Constraint:** Use Lo (2002) formula for Sharpe SE. Use bootstrap 10000 for CI.

---

### Task 7 — Frontend: Trade History page primary-metric overhaul

**File:** `frontend/src/pages/TradeHistory.jsx` (already built in prior sprint)

Add a new prominent panel at the top:

```jsx
<div className="arcis-card" style={{ borderTop: '3px solid var(--arcis-accent)' }}>
  <div className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-accent)' }}>
    Primary Metric: Excess-Return Sharpe (vs SPY)
  </div>
  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
    <div>
      <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Excess Sharpe</div>
      <div className="text-2xl font-medium" style={MONO}>
        {attribution.excess_sharpe?.toFixed(2) ?? '--'}
      </div>
      <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
        CI [{attribution.excess_sharpe_ci_low?.toFixed(2)}, {attribution.excess_sharpe_ci_high?.toFixed(2)}]
      </div>
    </div>
    <div>
      <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>t-statistic</div>
      <div className="text-2xl font-medium" style={MONO}>
        {attribution.excess_t_stat?.toFixed(2) ?? '--'}
      </div>
      <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
        Target: ≥ 2.0 for IB gate
      </div>
    </div>
    <div>
      <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Hit Rate vs SPY</div>
      <div className="text-2xl font-medium" style={MONO}>
        {attribution.hit_rate_vs_spy?.toFixed(0) ?? '--'}%
      </div>
      <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
        % of trades beating SPY
      </div>
    </div>
    <div>
      <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Verdict</div>
      <div className="text-sm font-medium" style={{ color: attribution.interpretation === 'alpha_significant' ? 'var(--arcis-success)' : 'var(--arcis-warning)' }}>
        {attribution.interpretation?.replace(/_/g, ' ') ?? '--'}
      </div>
    </div>
  </div>
</div>
```

**Also:** Add a secondary "Raw Sharpe (includes SPY beta)" panel below, demoted to smaller size, with a tooltip explaining the difference.

**Constraint:** New panel goes FIRST, above the "Today / Yesterday / 7d / 30d" cards. Excess-return IS the primary metric now.

---

### Task 8 — Dashboard.jsx: lead with excess-return Sharpe

**File:** `frontend/src/pages/Dashboard.jsx`

Find the current Sharpe display. Add the excess-Sharpe number adjacent to it with a visual comparison:

```
Raw Sharpe: 3.38  (includes SPY beta)
Excess Sharpe: 0.14  (alpha vs SPY)   ← primary metric
```

Use color to emphasize: excess-Sharpe in accent color, raw Sharpe demoted to muted gray.

---

### Task 9 — Regression tests

**File:** `tests/analytics/test_spy_benchmark.py` (new) — minimum 5 test cases
**File:** `tests/api/test_sharpe_attribution.py` (new) — minimum 3 test cases

Key tests:
1. `test_spy_return_over_range_known_dates` — 2026-03-24 to 2026-03-26 produces sensible SPY return
2. `test_spy_return_over_range_future_dates_returns_none` — graceful failure
3. `test_excess_return_positive_when_beating_spy` — pnl 5%, spy 2% → excess 3%
4. `test_excess_return_negative_when_underperforming_spy` — pnl 1%, spy 3% → excess -2%
5. `test_excess_return_none_when_spy_unavailable` — None in, None out
6. `test_sharpe_attribution_endpoint_returns_all_required_fields` — API contract
7. `test_interpretation_maps_t_correctly` — t=0.5 → "alpha_not_demonstrated", t=2.5 → "alpha_significant"
8. `test_backfill_is_idempotent` — running twice doesn't double-update

---

### Task 10 — Documentation updates

**Files:**
- `CHANGELOG.md` — add v0.19.0 entry
- `RELEASES.md` — add release notes
- `MASTER.md` Section 2 — update primary metric reference from "Sharpe" to "Excess Sharpe"
- `MASTER.md` Section 8 (gates) — update IB gate from "raw Sharpe ≥ 1.0" to "excess Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades"
- New doc: `docs/research/sharpe-attribution-methodology.md` — one-page explanation of why excess-Sharpe is primary, with formulas and example calculations

**CHANGELOG entry:**
```markdown
## v0.19.0 (TBD)

### Added
- **Excess-return Sharpe as primary metric.** All 78 closed trades backfilled with
  SPY-matched returns per SD#41 REVISED. New columns: spy_return_over_hold,
  excess_return, realized_sector. New endpoint /api/shadow/sharpe-attribution.
- Trade History and Dashboard pages lead with excess-Sharpe; raw Sharpe demoted.
- Manual GICS sector lookup at data/sp100-gics-lookup.csv (temporary until
  sector_context classifier is repaired per D3).

### Changed
- **IB live trading gate:** excess Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades
  (was raw Sharpe ≥ 1.0 which is trivially passed by SPY beta).
- Dashboard metric vocabulary: "Sharpe" → "Raw Sharpe (incl. SPY beta)" and
  "Excess Sharpe (alpha vs SPY)" — both shown, alpha-relevant is primary.

### Rationale
Forensic analysis of 78 trades revealed per-trade Sharpe 3.38 was mostly SPY
beta during a bull run. Excess vs SPY = +0.039% with t=0.098 over 75 matched
periods. Cannot claim alpha without this instrumentation.
```

---

## Success Criteria

1. All 78 existing closed trades have non-NULL `spy_return_over_hold`, `excess_return`, `realized_sector`
2. New closed trades auto-populate these fields on exit
3. `/api/shadow/sharpe-attribution` returns valid response with all required fields
4. Trade History page leads with excess-Sharpe panel
5. Dashboard shows both raw and excess Sharpe with clear visual hierarchy
6. All 8 new tests pass
7. `pytest tests/ --no-cov -q` passes fully (no regressions)
8. `cd frontend && npm run build` succeeds
9. No IB code touched (that's Sprint IB-cold-storage's job)

---

## Commit Messages

```
feat(schema): add spy_return_over_hold, excess_return, realized_sector to shadow_trades
feat(data): GICS sector lookup table for S&P 100 tickers
feat(analytics): SPY benchmark utility with yfinance integration
feat(scripts): backfill script for existing closed trades (idempotent)
feat(executor): populate SPY excess columns on every new exit
feat(api): /api/shadow/sharpe-attribution endpoint with raw+excess Sharpe
feat(frontend): Trade History page leads with excess-Sharpe primary metric
feat(frontend): Dashboard displays raw + excess Sharpe with visual hierarchy
test: SPY benchmark utility and Sharpe attribution endpoint
docs: SD#41 REVISED — excess-Sharpe is primary, IB gate redefined
```

---

## docs/sprint-checklist.md (final section)

- [ ] All 10 tasks completed
- [ ] 78+ trades backfilled with non-NULL excess_return
- [ ] `--dry-run` tested before actual backfill
- [ ] Idempotency verified (second run updates 0 rows)
- [ ] All 8 new tests pass
- [ ] No test regressions elsewhere
- [ ] Frontend builds clean
- [ ] `scripts/verify_docs.py` passes
- [ ] MASTER.md gate language updated
- [ ] CHANGELOG.md + RELEASES.md entries added
- [ ] README.md version badge updated
- [ ] Tag `v0.19.0` after merge
- [ ] Architecture diagram updated if it shows metric definitions

---

## Out-of-Scope

- Fixing the regime classifier (Sprint D3)
- Auditing attribution resolver (Sprint D2)
- Any Phase 1 optimization levers (all deferred until diagnostics complete)
- Refactoring executor.py (different sprint)
- Changing the GICS classifier beyond manual lookup CSV
- Rewriting raw-Sharpe display entirely (just demote visual weight; keep both)

---

## Ralph-Loop Review Questions

1. **Is the yfinance call rate-limited acceptable?** 78 backfill trades ≈ 78 API calls. Cache on first hit. Fine for one-time backfill.
2. **What if sector lookup CSV has typos?** Fallback to 'Unknown'; sprint emits warning. Fixable in follow-up.
3. **Does excess_return sign convention match convention?** pnl - spy = positive when beating SPY. Yes, standard.
4. **Is Lo 2002 the right SE formula?** Yes, standard for non-IID but approximately normal return series. Documented.
5. **Will the backfill block the watch loop?** No — runs as separate script, only INSERTs if called.

---

*Ready for 3× Ralph-loop review before CC execution.*
