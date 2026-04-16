# Sprint D1: SPY-Matched Excess Return Instrumentation (FINAL)

**Authority:** SD#41 REVISED `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
**Effort:** 1 weekend (8-10 hours CC time)
**Branch:** `feat/spy-excess-instrumentation`
**Tag on merge:** `v0.19.0`
**Priority:** CRITICAL — blocks all Phase 1 optimization
**Ralph-loop status:** Pass 3 complete, grounded in actual repo structure

---

## Goal

Make every Sharpe metric in Arcis answer "alpha or SPY beta?" Add three columns to `shadow_trades` for SPY-matched excess returns. Backfill all existing closed trades. Expose excess-Sharpe as the primary metric on dashboard and API. Redefine the IB live-trading gate from raw Sharpe ≥ 1.0 (trivially passed by SPY beta) to excess-return Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades.

---

## Background Context for CC

- **Dataset snapshot:** 78+ closed trades in `shadow_trades`, date range ~2026-03-24 to now
- **Current headline metric:** Per-trade Sharpe 3.38 [CI 2.80, 3.96]. Looks great in isolation.
- **Hidden truth:** Forensic analysis (`docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf` §6) shows mean excess vs SPY = +0.039% per trade, t=0.098. Per-trade Sharpe reflects SPY drift capture, not alpha.
- **Redefined gate:** Raw Sharpe gate is deprecated. Excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades is the new IB gate.

Infrastructure that already exists in the repo (confirmed via Pass 1 audit):
- DB access pattern: `import sqlite3` then `sqlite3.connect(DB_PATH)` with `from src.config import DB_PATH`
- Schema: `src/schema/registry.py` with `ColumnDef` pattern — new columns added as additional `ColumnDef` entries in the `shadow_trades` TableDef
- yfinance already used at `src/data_ingestion/market_data.py` and `src/attribution/logger.py:195` — follow the existing download patterns
- Config loads via `from src.config import load_config` from `config/settings.local.yaml`
- `src/universe/sp100.py` has canonical S&P 100 ticker list
- `src/journal/store.py` owns `shadow_trades` writes — any new column on `shadow_trades` must also be allowed there

---

## Pre-Flight Checks

```bash
# 1. Verify yfinance works
python -c "import yfinance as yf; print(yf.Ticker('SPY').history(period='5d').tail())"

# 2. Confirm DB_PATH accessible
python -c "from src.config import DB_PATH; import sqlite3; conn = sqlite3.connect(DB_PATH); print([r[1] for r in conn.execute('PRAGMA table_info(shadow_trades)').fetchall()])"

# 3. Confirm new columns don't already exist
python -c "from src.config import DB_PATH; import sqlite3; conn = sqlite3.connect(DB_PATH); cols = [r[1] for r in conn.execute('PRAGMA table_info(shadow_trades)').fetchall()]; new = ['spy_return_over_hold', 'excess_return', 'realized_sector']; [print(f'{c}: EXISTS' if c in cols else f'{c}: missing') for c in new]"

# 4. Trade count
python -c "from src.config import DB_PATH; import sqlite3; conn = sqlite3.connect(DB_PATH); print('Closed trades:', conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE actual_exit_time IS NOT NULL').fetchone()[0])"

# 5. Branch
git status && git branch --show-current
git checkout -b feat/spy-excess-instrumentation
```

---

## Task List

### Task 1 — Add columns to `shadow_trades` schema

**File:** `src/schema/registry.py`

Find the `TableDef` for `shadow_trades` (grep for `name="shadow_trades"`). Add three `ColumnDef` entries immediately after `ColumnDef("max_adverse_excursion", "REAL")`, before `ColumnDef("duration_days", "INTEGER")`:

```python
ColumnDef("spy_return_over_hold", "REAL",
          description="SPY total return (close-to-close, auto-adjusted) over the "
                      "exact entry-to-exit date range. SD#41 REVISED — foundation "
                      "for alpha vs beta measurement."),
ColumnDef("excess_return", "REAL",
          description="pnl_pct - (spy_return_over_hold * 100). Positive means "
                      "beat SPY over same period. Primary alpha metric; raw "
                      "pnl_pct is secondary."),
ColumnDef("realized_sector", "TEXT",
          description="GICS sector from manual lookup at data/sp100-gics-lookup.csv. "
                      "Temporary until sector_context classifier (Sprint D3) is fixed."),
```

Schema migration applies automatically on next DB initialization (see existing ALTER TABLE pattern in `src/schema/`).

**Also update `src/journal/store.py`** — its `_filter_to_schema` function reads the registry, so no changes needed there. But verify by grepping for any hardcoded column allow-list that excludes the new names.

**Constraint:** Do not reorder or rename existing columns. Pure additive change.

---

### Task 2 — Build GICS sector lookup CSV

**File:** `data/sp100-gics-lookup.csv` (new)

Two columns: `ticker,gics_sector`. Use one of the 11 GICS sector names: `Technology`, `Health Care`, `Financials`, `Consumer Discretionary`, `Consumer Staples`, `Industrials`, `Energy`, `Utilities`, `Real Estate`, `Materials`, `Communication Services`.

**Approach:** First pass via `yfinance.Ticker(sym).info.get('sector')`, then manual review. The S&P 100 universe lives in `src/universe/sp100.py` — use that as the authoritative ticker list (grep for `SP100_TICKERS` or similar).

**No "Unknown" entries** in the committed CSV — if yfinance fails for a ticker, manually classify based on the company's primary business.

**Validation:**
```bash
python -c "
import csv
lookup = {row['ticker']: row['gics_sector'] for row in csv.DictReader(open('data/sp100-gics-lookup.csv'))}
print(f'Rows: {len(lookup)}')
print(f'Unique sectors: {sorted(set(lookup.values()))}')
"
```
Expect ~100-102 rows and exactly 11 sectors.

---

### Task 3 — SPY benchmark utility

**File:** `src/analytics/spy_benchmark.py` (new; create `src/analytics/__init__.py` too)

```python
"""SPY-matched excess return calculations — SD#41 REVISED.

Converts Sharpe metrics from raw to excess by subtracting SPY's return
over the same date range. Distinguishes alpha from bull-market beta drift.

Called by: shadow_trading.executor (on exit), shadow_trading.reconcile,
           scripts.backfill_spy_excess, api.cloud_routes.trades
Owns tables: none (writes via journal.store)
Config keys: none
Tests: tests/analytics/test_spy_benchmark.py
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SECTOR_LOOKUP_PATH = Path("data/sp100-gics-lookup.csv")


@lru_cache(maxsize=1)
def _load_sector_lookup() -> dict[str, str]:
    if not _SECTOR_LOOKUP_PATH.exists():
        logger.warning("[SPY_BENCH] Sector lookup missing: %s", _SECTOR_LOOKUP_PATH)
        return {}
    with _SECTOR_LOOKUP_PATH.open() as f:
        return {row["ticker"]: row["gics_sector"] for row in csv.DictReader(f)}


def get_sector(ticker: str) -> Optional[str]:
    """Return GICS sector for ticker; None if unknown."""
    return _load_sector_lookup().get(ticker.upper())


def spy_return_over_range(entry_iso: str, exit_iso: str) -> Optional[float]:
    """SPY total return (fraction) from entry close to exit close.

    Returns None if data unavailable — callers treat as 'cannot attribute',
    NOT 'zero return'. Fail-open: never blocks exit finalization.
    """
    try:
        import yfinance as yf
        entry_date = dt.datetime.fromisoformat(entry_iso.replace("Z", "+00:00")).date()
        exit_date = dt.datetime.fromisoformat(exit_iso.replace("Z", "+00:00")).date()

        # Buffer on both sides to handle weekends/holidays
        start = (entry_date - dt.timedelta(days=5)).isoformat()
        end = (exit_date + dt.timedelta(days=5)).isoformat()

        data = yf.download("SPY", start=start, end=end,
                           progress=False, auto_adjust=True)
        if data.empty:
            return None

        df = data.reset_index()
        df["date"] = df["Date"].dt.date

        at_or_after_entry = df[df["date"] >= entry_date]
        at_or_after_exit = df[df["date"] >= exit_date]
        if at_or_after_entry.empty or at_or_after_exit.empty:
            return None

        entry_close = float(at_or_after_entry.iloc[0]["Close"])
        exit_close = float(at_or_after_exit.iloc[0]["Close"])
        return (exit_close - entry_close) / entry_close
    except Exception as exc:
        logger.warning("[SPY_BENCH] spy_return_over_range(%s,%s) failed: %s",
                       entry_iso, exit_iso, exc)
        return None


def excess_return(pnl_pct: Optional[float],
                  spy_return_fraction: Optional[float]) -> Optional[float]:
    """Excess = pnl_pct - (spy_return * 100). Both in percent units."""
    if pnl_pct is None or spy_return_fraction is None:
        return None
    return pnl_pct - (spy_return_fraction * 100.0)
```

File size: ≤ 130 lines.

---

### Task 4 — Tests for SPY benchmark

**File:** `tests/analytics/test_spy_benchmark.py` (new; create `tests/analytics/__init__.py`)

```python
"""Tests for SPY benchmark utility (D1)."""

import pytest
import pandas as pd
from unittest.mock import patch

from src.analytics.spy_benchmark import (
    spy_return_over_range, excess_return, get_sector, _load_sector_lookup,
)


def test_excess_return_positive_when_beating_spy():
    assert excess_return(5.0, 0.02) == pytest.approx(3.0)


def test_excess_return_negative_when_losing_to_spy():
    assert excess_return(1.0, 0.03) == pytest.approx(-2.0)


def test_excess_return_none_when_spy_unavailable():
    assert excess_return(1.0, None) is None


def test_excess_return_none_when_pnl_none():
    assert excess_return(None, 0.02) is None


def test_spy_return_handles_empty_yfinance_response():
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame()
        assert spy_return_over_range(
            "2026-01-01T10:00:00", "2026-01-05T10:00:00"
        ) is None


def test_spy_return_handles_exception_gracefully():
    with patch("yfinance.download", side_effect=Exception("net")):
        assert spy_return_over_range(
            "2026-01-01T10:00:00", "2026-01-05T10:00:00"
        ) is None


def test_get_sector_returns_none_for_unknown_ticker():
    _load_sector_lookup.cache_clear()
    assert get_sector("FAKEZZ") is None
```

---

### Task 5 — Backfill script

**File:** `scripts/backfill_spy_excess.py` (new, ≤ 100 lines)

```python
"""Backfill spy_return_over_hold, excess_return, realized_sector for
all existing closed trades. Idempotent — safe to re-run.

Usage:
    python scripts/backfill_spy_excess.py [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import logging
import sqlite3

from src.config import DB_PATH
from src.analytics.spy_benchmark import (
    spy_return_over_range, excess_return, get_sector,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backfill(dry_run: bool = False, force: bool = False) -> dict:
    updated = skipped_existing = skipped_no_spy = 0
    unknown_sectors = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT trade_id, ticker, actual_entry_time, actual_exit_time, "
            "pnl_pct, spy_return_over_hold, excess_return, realized_sector "
            "FROM shadow_trades "
            "WHERE actual_exit_time IS NOT NULL AND pnl_pct IS NOT NULL"
        ).fetchall()
        logger.info("Candidates: %d closed trades", len(rows))

        for row in rows:
            all_present = (row["spy_return_over_hold"] is not None
                           and row["excess_return"] is not None
                           and row["realized_sector"] is not None)
            if not force and all_present:
                skipped_existing += 1
                continue

            spy_ret = spy_return_over_range(
                row["actual_entry_time"], row["actual_exit_time"]
            )
            if spy_ret is None:
                skipped_no_spy += 1
                continue

            excess = excess_return(row["pnl_pct"], spy_ret)
            sector = get_sector(row["ticker"]) or "Unknown"
            if sector == "Unknown":
                unknown_sectors.append(row["ticker"])

            if dry_run:
                logger.info("[DRY] %s pnl=%.2f%% spy=%.2f%% excess=%.2f%% sector=%s",
                            row["ticker"], row["pnl_pct"],
                            spy_ret * 100, excess, sector)
            else:
                conn.execute(
                    "UPDATE shadow_trades "
                    "SET spy_return_over_hold=?, excess_return=?, realized_sector=? "
                    "WHERE trade_id=?",
                    (spy_ret, excess, sector, row["trade_id"])
                )
                updated += 1

        if not dry_run:
            conn.commit()

    result = dict(updated=updated, skipped_existing=skipped_existing,
                  skipped_no_spy=skipped_no_spy,
                  unknown_sectors=unknown_sectors)
    logger.info("Backfill complete: %s", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, force=args.force)
```

Validation:
```bash
python scripts/backfill_spy_excess.py --dry-run 2>&1 | tail -3
python scripts/backfill_spy_excess.py 2>&1 | tail -3
# Idempotency
python scripts/backfill_spy_excess.py 2>&1 | tail -3  # updated=0
```

---

### Task 6 — Hook into exit path

**Files:** `src/shadow_trading/executor.py` AND `src/shadow_trading/reconcile.py`

Exits are finalized in both files. Find the code paths that populate `pnl_pct` at exit (grep `pnl_pct` in both files — there should be 2-4 call sites). At each, add:

```python
from src.analytics.spy_benchmark import (
    spy_return_over_range, excess_return, get_sector,
)

# Where pnl_pct is computed on exit:
if actual_entry_time and actual_exit_time:
    spy_ret = spy_return_over_range(actual_entry_time, actual_exit_time)
    trade_data["spy_return_over_hold"] = spy_ret
    trade_data["excess_return"] = excess_return(pnl_pct, spy_ret)
    trade_data["realized_sector"] = get_sector(ticker)
```

**Critical:** Write all three fields even if `spy_ret` is None (just None values). This keeps the column state consistent. `journal.store` already filters unknown columns via `_filter_to_schema`, so the update is safe.

**Constraint:** Never fail the exit due to SPY fetch error. SPY fetch timeout should be ≤ 5s; if it hangs, accept None.

Verify after deployment by exiting a trade and querying:
```bash
python -c "from src.config import DB_PATH; import sqlite3; c = sqlite3.connect(DB_PATH); print(c.execute('SELECT ticker, pnl_pct, spy_return_over_hold, excess_return, realized_sector FROM shadow_trades WHERE actual_exit_time IS NOT NULL ORDER BY actual_exit_time DESC LIMIT 5').fetchall())"
```

---

### Task 6b — Add new REAL columns to render_sync type coercion

**File:** `src/sync/render_sync.py`

The sync layer uses `SELECT *` from SQLite (good — new columns are picked up automatically). But it has hardcoded `_REAL_COLUMNS` and `_INTEGER_COLUMNS` sets (~line 267) for type coercion before Postgres INSERT. SQLite stores everything as TEXT; Postgres needs proper types.

Find `_REAL_COLUMNS` (around line 274) and add the two new REAL columns:

```python
_REAL_COLUMNS = {
    "actual_entry_price", "actual_exit_price", "pnl_dollars", "pnl_pct",
    "stop_price", "target_1", "target_2",
    "entry_price", "signal_price", "signal_entry_price", "signal_exit_price",
    "fill_entry_price", "fill_exit_price",
    "priority_score", "confidence_score", "position_size_dollars",
    "position_size_pct", "estimated_dollar_risk", "pullback_depth_pct", "atr",
    "max_favorable_excursion", "max_adverse_excursion", "planned_allocation",
    "spy_return_over_hold", "excess_return",  # SD#41 D1
}
```

`realized_sector` is TEXT — no coercion needed; passes through fine.

**Why this matters:** Without this, backfilled data stays in local SQLite but doesn't reliably sync to Render Postgres, which means the dashboard at halcyonlab.app won't show the new metrics. The Postgres schema auto-creates new columns from the registry, but the data INSERT can fail on type mismatch if the coercion set is incomplete.

**Constraint:** Do not change any other entries in _REAL_COLUMNS or _INTEGER_COLUMNS.

---

### Task 7 — New API endpoint

**File:** `src/api/cloud_routes/trades.py` (add to existing router)

Add after `/api/shadow/closed`:

```python
@router.get("/api/shadow/sharpe-attribution",
            dependencies=[Depends(verify_auth)])
def get_sharpe_attribution(runtime: Runtime = Depends(get_runtime)):
    """SD#41 REVISED primary metric: alpha vs SPY beta.

    Returns raw Sharpe AND excess Sharpe with confidence intervals and
    t-statistic. Excess is primary; raw is secondary.
    """
    try:
        rows = runtime.query(
            "SELECT pnl_pct, spy_return_over_hold, excess_return "
            "FROM shadow_trades "
            "WHERE actual_exit_time IS NOT NULL AND pnl_pct IS NOT NULL"
        )
        if not rows or len(rows) < 2:
            return {"error": "insufficient_data",
                    "n_trades": len(rows or [])}

        def sharpe(values, n_per_year=150.0):
            if len(values) < 2:
                return None, None
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            std = var ** 0.5
            if std == 0:
                return 0.0, 0.0
            sr = (mean / std) * (n_per_year ** 0.5)
            se = ((1 + 0.5 * sr ** 2) / len(values)) ** 0.5
            return sr, se

        pnl = [r["pnl_pct"] for r in rows]
        raw_sr, raw_se = sharpe(pnl)

        excess_values = [r["excess_return"] for r in rows
                         if r["excess_return"] is not None]
        n_with_spy = len(excess_values)
        if n_with_spy < 2:
            return {
                "n_trades": len(rows),
                "trades_with_spy_data": n_with_spy,
                "raw_sharpe": round(raw_sr, 3),
                "excess_sharpe": None,
                "interpretation": "insufficient_spy_data",
            }

        ex_sr, ex_se = sharpe(excess_values)
        mean_excess = sum(excess_values) / len(excess_values)
        std_excess = (sum((v - mean_excess) ** 2 for v in excess_values)
                      / (len(excess_values) - 1)) ** 0.5
        t_stat = (mean_excess / (std_excess / (n_with_spy ** 0.5))
                  if std_excess > 0 else 0.0)
        hit_rate = (sum(1 for v in excess_values if v > 0)
                    / n_with_spy * 100)

        if abs(t_stat) < 1.0:
            interp = "alpha_not_demonstrated"
        elif abs(t_stat) < 2.0:
            interp = "alpha_suggestive" if t_stat > 0 else "negative_alpha_suggestive"
        else:
            interp = "alpha_significant" if t_stat > 0 else "negative_alpha_significant"

        return {
            "n_trades": len(rows),
            "trades_with_spy_data": n_with_spy,
            "trades_missing_spy_data": len(rows) - n_with_spy,
            "raw_sharpe": round(raw_sr, 3),
            "raw_sharpe_ci_low": round(raw_sr - 1.96 * raw_se, 3),
            "raw_sharpe_ci_high": round(raw_sr + 1.96 * raw_se, 3),
            "excess_sharpe": round(ex_sr, 3),
            "excess_sharpe_ci_low": round(ex_sr - 1.96 * ex_se, 3),
            "excess_sharpe_ci_high": round(ex_sr + 1.96 * ex_se, 3),
            "excess_t_stat": round(t_stat, 3),
            "mean_excess_pct": round(mean_excess, 3),
            "hit_rate_vs_spy": round(hit_rate, 1),
            "interpretation": interp,
        }
    except Exception as exc:
        runtime.logger.error("[API] sharpe-attribution failed: %s", exc)
        return {"error": str(exc)}
```

**File:** `frontend/src/api.js` — add:
```javascript
getSharpeAttribution: () => fetchApi('/shadow/sharpe-attribution'),
```

---

### Task 8 — Trade History page: excess-Sharpe lead panel

**File:** `frontend/src/pages/TradeHistory.jsx`

Add a new `useQuery` for attribution, render a new panel BEFORE the Today/Yesterday/7d/30d cards:

```jsx
// Near top of component — new useQuery alongside existing ones:
const { data: attribution } = useQuery({
  queryKey: ['sharpe-attribution'],
  queryFn: api.getSharpeAttribution,
  refetchInterval: 60000,
})

// Helper near other helpers:
const verdictColor = (interp) => {
  if (!interp) return 'var(--arcis-text-muted)'
  if (interp === 'alpha_significant') return 'var(--arcis-success)'
  if (interp === 'alpha_suggestive') return 'var(--arcis-warning)'
  return 'var(--arcis-danger)'
}

// In render, BEFORE the recency cards grid:
{attribution && !attribution.error && (
  <div className="arcis-card" style={{ borderTop: '3px solid var(--arcis-accent)' }}>
    <div className="flex items-center justify-between mb-2">
      <div className="text-xs uppercase tracking-wide"
           style={{ color: 'var(--arcis-accent)' }}>
        Primary Metric: Excess-Return Sharpe (vs SPY)
      </div>
      <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
        SD#41 REVISED
      </div>
    </div>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
      <div>
        <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          Excess Sharpe
        </div>
        <div className="text-2xl font-medium" style={MONO}>
          {attribution.excess_sharpe?.toFixed(2) ?? '--'}
        </div>
        <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
          {attribution.excess_sharpe_ci_low != null
            ? `CI [${attribution.excess_sharpe_ci_low.toFixed(2)}, ${attribution.excess_sharpe_ci_high.toFixed(2)}]`
            : 'insufficient data'}
        </div>
      </div>
      <div>
        <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          t-statistic
        </div>
        <div className="text-2xl font-medium" style={MONO}>
          {attribution.excess_t_stat?.toFixed(2) ?? '--'}
        </div>
        <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
          IB gate: ≥ 2.0
        </div>
      </div>
      <div>
        <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          Beat SPY
        </div>
        <div className="text-2xl font-medium" style={MONO}>
          {attribution.hit_rate_vs_spy?.toFixed(0) ?? '--'}%
        </div>
        <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
          hit rate
        </div>
      </div>
      <div>
        <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          Verdict
        </div>
        <div className="text-sm font-medium mt-1"
             style={{ color: verdictColor(attribution.interpretation) }}>
          {(attribution.interpretation || '--').replace(/_/g, ' ')}
        </div>
        <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
          Raw Sharpe: {attribution.raw_sharpe?.toFixed(2)} (alpha+beta)
        </div>
      </div>
    </div>
  </div>
)}
```

Raw Sharpe still visible but visually demoted (small text, secondary color).

---

### Task 9 — Documentation

- `CHANGELOG.md` — add v0.19.0 entry
- `RELEASES.md` — release notes
- `MASTER.md` — Section 2 (add "SPY-matched excess instrumentation: ENABLED") + gates section (redefine IB gate)
- `README.md` — version badge
- `docs/research/sharpe-attribution-methodology.md` (new, ~1 page) — one-page methodology reference with formulas

**CHANGELOG:**
```markdown
## v0.19.0

### Added — SD#41 REVISED D1
- Three new columns on `shadow_trades`: `spy_return_over_hold`,
  `excess_return`, `realized_sector`
- `src/analytics/spy_benchmark.py` — SPY return + sector lookup utility
- `scripts/backfill_spy_excess.py` — idempotent historical backfill
- `/api/shadow/sharpe-attribution` — primary metric endpoint with CIs
- Trade History page leads with excess-Sharpe panel
- `data/sp100-gics-lookup.csv` — manual GICS mapping (temporary until D3)

### Changed
- **IB live trading gate redefined:** excess-return Sharpe ≥ 0.5 at
  t ≥ 2.0 over 150 OOS trades (was raw Sharpe ≥ 1.0, trivially passed
  by SPY beta)

### Rationale
Forensic analysis of 78 closed trades showed per-trade Sharpe 3.38 was
mostly SPY beta during a bull run. Excess vs SPY = +0.039%, t=0.098
over 75 matched periods. Without this instrumentation we cannot
distinguish alpha from beta.
```

---

### Task 10 — Checklist

```bash
pytest -q tests/analytics/ tests/ --no-cov 2>&1 | tail -10
python scripts/backfill_spy_excess.py --dry-run 2>&1 | tail -3
python scripts/backfill_spy_excess.py 2>&1 | tail -3

python -c "from src.config import DB_PATH; import sqlite3; c = sqlite3.connect(DB_PATH); n_with = c.execute('SELECT COUNT(*) FROM shadow_trades WHERE excess_return IS NOT NULL AND actual_exit_time IS NOT NULL').fetchone()[0]; n_closed = c.execute('SELECT COUNT(*) FROM shadow_trades WHERE actual_exit_time IS NOT NULL').fetchone()[0]; print(f'Backfilled: {n_with}/{n_closed}')"

cd frontend && npm run build && cd ..
python scripts/verify_docs.py 2>&1 | tail -3
git push origin feat/spy-excess-instrumentation
```

---

## Success Criteria

1. All closed trades have non-NULL `excess_return` and `realized_sector` (within constraints of SPY data availability)
2. New trades populate the three fields on exit automatically
3. `/api/shadow/sharpe-attribution` returns valid payload
4. Trade History page shows Excess-Sharpe panel prominently
5. 7 new tests pass
6. No regressions (`pytest --no-cov` passes)
7. `npm run build` succeeds
8. `scripts/verify_docs.py` passes

---

## Out-of-Scope

- D2/D3/H1 work (parallel sprints)
- IB code
- Dashboard.jsx full metric overhaul (follow-up sprint)
- Rebuilding the attribution resolver (SD#41 Sprint D2)

---

## 3× Ralph-Loop Summary

**Pass 1 (repo audit):** Found `get_db()` doesn't exist (use `sqlite3.connect(DB_PATH)`), confirmed schema pattern, confirmed yfinance usage pattern, confirmed `src/journal/store.py` owns writes.

**Pass 2 (spec correction):** Rewrote DB access, inlined helper code, added dual-path hook (executor AND reconcile), added `lru_cache` to sector lookup, explicit fail-open semantics for SPY fetch.

**Pass 3 (minimize scope):** Removed ambitious Dashboard.jsx overhaul (follow-up sprint). Tightened file-size caps. Clarified idempotency test. Ensured three fields are always written together (all-or-nothing semantics).

**Final confidence:** HIGH. Ready for CC.
