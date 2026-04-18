# Regime Diagnostic v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether the incumbent strategy's zero excess-Sharpe is driven by a specific contaminant (sector, time-of-day, day-cluster) or uniformly distributed, producing a CONTAMINATED / UNIFORMLY_NULL / PENDING decision.

**Architecture:** Modular library under `src/diagnostics/` with thin CLI at `scripts/diagnostics/regime_diagnostic_v1.py`. Each module handles one concern (dimensions, bootstrap, FDR, power, analyses, plots, report). No DB writes — all analysis is read-only with in-memory VIX backfill. yfinance data cached to `.tmp/regime_diagnostic_cache/`.

**Tech Stack:** Python 3.12, sqlite3, numpy, scipy, matplotlib, yfinance, pandas

**Spec:** `docs/superpowers/specs/2026-04-18-regime-diagnostic-v1-design.md`

---

## Data Profile (from exploration)

These numbers inform test design and expected outputs:

- **N = 88 closed trades** (27 non-quarantined + 61 quarantined from April 10 cascade)
- **Trade window:** entries 2026-03-24 to 2026-04-13, exits to 2026-04-17
- **Entry days with trades:** 8 calendar days (Mar 24, 27, 31, Apr 1, 7, 8, 9, 13)
- **VIX range (populated):** 19.2 to 24.2 (5-point range, very narrow)
- **Sectors:** 11 GICS, collapsing to 4 buckets (Tech+Comm: 16, Financials: 11, Defensive: 31, Cyclical: 30)
- **Entry hours:** concentrated in 09-10 AM (47 trades) and 16 (20 trades)
- **Duration:** short(1-3): 54, medium(4-6): 25, long(7+): 9
- **Mean excess return:** -0.345% (all 88), +0.721% (27 non-quarantined)
- **Entry timestamps:** ISO with TZ, e.g., `2026-03-24T10:01:20.667918-04:00`
- **DB path:** `C:/arcis/data/ai_research_desk.sqlite3`
- **quarantined column:** integer 0/1

**Quarantine note:** The forensic audit's "85 closed trades" included quarantined trades (count has since grown to 88). The primary analysis uses all 88. The CLI accepts `--exclude-quarantined` to re-run on the 27 non-quarantined as a sensitivity check. Both results are discussed in the report if materially different.

---

## File Structure

```
src/diagnostics/
  __init__.py           ~5 lines    Package marker
  dimensions.py         ~150 lines  Load trades, VIX backfill, sector/hour/duration bucketing
  known_events.py       ~35 lines   Dict of dates -> event labels for Mar-Apr 2026
  bootstrap.py          ~70 lines   Bootstrap CI engine (10K resamples)
  fdr.py                ~35 lines   Benjamini-Hochberg FDR correction
  power.py              ~80 lines   MDE for cells + regression slope
  analyses.py           ~250 lines  A1-A5 analysis functions
  plots.py              ~200 lines  6 matplotlib figures
  report.py             ~250 lines  Markdown report generator

scripts/diagnostics/
  regime_diagnostic_v1.py  ~100 lines  CLI entry point

tests/diagnostics/
  __init__.py
  test_regime_diagnostic.py  ~350 lines  14 tests
```

---

## Task 1: Dimensions + VIX Backfill + Known Events + Tests

**Files:**
- Create: `src/diagnostics/__init__.py`
- Create: `src/diagnostics/dimensions.py`
- Create: `src/diagnostics/known_events.py`
- Create: `tests/diagnostics/__init__.py`
- Create: `tests/diagnostics/test_regime_diagnostic.py` (first 5 tests)

### Step-by-step

- [ ] **Step 1: Create package markers**

```bash
mkdir -p src/diagnostics tests/diagnostics
```

Create `src/diagnostics/__init__.py`:
```python
"""Diagnostics — statistical analysis tools for strategy evaluation.

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: none (leaf package)
Owns tables: none (read-only)
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""
```

Create `tests/diagnostics/__init__.py` as empty file.

- [ ] **Step 2: Create known_events.py**

Create `src/diagnostics/known_events.py`:
```python
"""Known macro events for the March-April 2026 trade window.

Called by: diagnostics.analyses
Calls: none
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

# Dict of ISO date string -> event label.
# Used by day-clustering analysis (A2 tertiary) to determine whether
# a bad-day cluster maps to a repeatable event category.
KNOWN_EVENTS: dict[str, str] = {
    # March 2026
    "2026-03-18": "FOMC_DECISION",
    "2026-03-19": "FOMC_DECISION",  # statement + press conference day
    "2026-03-28": "QUARTER_END_REBALANCE",
    # April 2026
    "2026-04-02": "TARIFF_ANNOUNCEMENT",  # Liberation Day reciprocal tariffs
    "2026-04-03": "NFP_FRIDAY",
    "2026-04-04": "TARIFF_ESCALATION",  # China retaliation announced
    "2026-04-07": "TARIFF_ESCALATION",  # Market crash continuation
    "2026-04-09": "TARIFF_PAUSE",  # 90-day pause announced
    "2026-04-10": "CPI_PRINT",
    "2026-04-11": "PPI_PRINT",
    "2026-04-17": "OPEX_WEEKLY",
    "2026-04-18": "OPEX_MONTHLY",
}

# Categories for grouping events in the report
EVENT_CATEGORIES: dict[str, str] = {
    "FOMC_DECISION": "Monetary Policy",
    "TARIFF_ANNOUNCEMENT": "Trade Policy",
    "TARIFF_ESCALATION": "Trade Policy",
    "TARIFF_PAUSE": "Trade Policy",
    "NFP_FRIDAY": "Employment Data",
    "CPI_PRINT": "Inflation Data",
    "PPI_PRINT": "Inflation Data",
    "OPEX_WEEKLY": "Options Expiration",
    "OPEX_MONTHLY": "Options Expiration",
    "QUARTER_END_REBALANCE": "Calendar Effect",
}
```

- [ ] **Step 3: Write the first 5 failing tests**

Create `tests/diagnostics/test_regime_diagnostic.py`:
```python
"""Tests for regime diagnostic v1.

Tests organized by module: dimensions, bootstrap, fdr, power, analyses.
Each test is self-contained with synthetic data — no DB dependency.
"""

import numpy as np
import pytest
from datetime import datetime, timezone, timedelta


# ── dimensions tests ──────────────────────────────────────────────


def test_vix_backfill_no_nulls():
    """VIX backfill produces no NULLs for trades within yfinance range."""
    from src.diagnostics.dimensions import backfill_vix

    trades = [
        {"trade_id": "t1", "actual_entry_time": "2026-03-24T10:00:00-04:00",
         "vix_at_entry": None},
        {"trade_id": "t2", "actual_entry_time": "2026-04-01T10:00:00-04:00",
         "vix_at_entry": 21.5},
    ]
    # Mock VIX data: a simple series covering the window
    import pandas as pd
    dates = pd.bdate_range("2026-03-01", "2026-04-18")
    vix_series = pd.Series(
        np.linspace(18.0, 25.0, len(dates)), index=dates, name="Close"
    )
    result = backfill_vix(trades, vix_series)
    assert all(t["vix_at_entry"] is not None for t in result)
    # t2's existing value should be preserved
    assert result[1]["vix_at_entry"] == 21.5


def test_vix_crosscheck_flags_discrepancy():
    """Cross-check flags vix_at_entry values differing >0.5 from yfinance."""
    from src.diagnostics.dimensions import crosscheck_vix

    trades = [
        {"trade_id": "t1", "actual_entry_time": "2026-03-24T10:00:00-04:00",
         "vix_at_entry": 20.0},
        {"trade_id": "t2", "actual_entry_time": "2026-03-25T10:00:00-04:00",
         "vix_at_entry": 22.0},
    ]
    import pandas as pd
    dates = pd.bdate_range("2026-03-20", "2026-03-28")
    vix_series = pd.Series(
        [19.0, 19.0, 20.1, 20.2, 25.0, 25.0, 25.0, 25.0, 25.0][:len(dates)],
        index=dates, name="Close",
    )
    flags = crosscheck_vix(trades, vix_series)
    # t1: |20.0 - 20.2| = 0.2 < 0.5 -> no flag
    # t2: |22.0 - 25.0| = 3.0 > 0.5 -> flagged
    assert len(flags) == 1
    assert flags[0]["trade_id"] == "t2"


def test_sector_collapse_maps_all_gics():
    """All 11 GICS sectors map to exactly 4 buckets."""
    from src.diagnostics.dimensions import collapse_sector

    all_gics = [
        "Technology", "Communication Services",
        "Financials",
        "Health Care", "Consumer Staples", "Utilities",
        "Industrials", "Energy", "Materials",
        "Consumer Discretionary", "Real Estate",
    ]
    buckets = {collapse_sector(s) for s in all_gics}
    assert buckets == {"Tech+Comm", "Financials", "Defensive", "Cyclical"}


def test_entry_hour_bucket_handles_timezone():
    """Entry hour bucketing parses timezone-aware ISO timestamps."""
    from src.diagnostics.dimensions import entry_hour_bucket

    # 09:58 ET -> bucket "09:30-10:30"
    assert entry_hour_bucket("2026-03-24T09:58:34.137074-04:00") == "09:30-10:30"
    # 14:46 ET -> bucket "14:00-16:00"
    assert entry_hour_bucket("2026-04-13T14:46:48.351956-04:00") == "14:00-16:00"
    # 10:38 ET -> bucket "10:30-12:00"
    assert entry_hour_bucket("2026-04-01T10:38:07.650905-04:00") == "10:30-12:00"
    # 12:30 ET -> bucket "12:00-14:00"
    assert entry_hour_bucket("2026-04-02T12:30:00.000000-04:00") == "12:00-14:00"


def test_holding_period_bucket_edge_cases():
    """Holding period bucketing handles edge cases."""
    from src.diagnostics.dimensions import holding_period_bucket

    assert holding_period_bucket(0) == "short"
    assert holding_period_bucket(1) == "short"
    assert holding_period_bucket(3) == "short"
    assert holding_period_bucket(4) == "medium"
    assert holding_period_bucket(6) == "medium"
    assert holding_period_bucket(7) == "long"
    assert holding_period_bucket(15) == "long"
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py -v
```

Expected: 5 FAILED (ImportError — modules don't exist yet)

- [ ] **Step 5: Implement dimensions.py**

Create `src/diagnostics/dimensions.py`:
```python
"""Trade dimension computation for regime diagnostic.

Loads closed trades from shadow_trades, backfills missing vix_at_entry
via yfinance, and computes sector/hour/holding-period buckets. All
computation is in-memory — no DB writes.

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: yfinance (via cache), known_events
Owns tables: none (read-only)
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

CACHE_DIR = Path(".tmp/regime_diagnostic_cache")

SECTOR_MAP = {
    "Technology": "Tech+Comm",
    "Communication Services": "Tech+Comm",
    "Financials": "Financials",
    "Health Care": "Defensive",
    "Consumer Staples": "Defensive",
    "Utilities": "Defensive",
    "Industrials": "Cyclical",
    "Energy": "Cyclical",
    "Materials": "Cyclical",
    "Consumer Discretionary": "Cyclical",
    "Real Estate": "Cyclical",
}


def load_closed_trades(
    db_path: str, *, exclude_quarantined: bool = False,
) -> list[dict]:
    """Load closed trades with exit and pnl from shadow_trades."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where = (
        "actual_exit_time IS NOT NULL AND pnl_pct IS NOT NULL"
    )
    if exclude_quarantined:
        where += " AND quarantined = 0"
    rows = conn.execute(
        f"SELECT trade_id, ticker, actual_entry_time, actual_exit_time, "
        f"duration_days, pnl_pct, excess_return, vix_at_entry, "
        f"realized_sector, quarantined "
        f"FROM shadow_trades WHERE {where}"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_vix_daily(cache_dir: Path = CACHE_DIR) -> pd.Series:
    """Fetch ^VIX daily closes via yfinance with file cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "vix_daily.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        return df["Close"].squeeze()
    import yfinance as yf
    df = yf.download(
        "^VIX", start="2025-09-01", end="2026-04-20", progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.to_parquet(cache_file)
    return df["Close"]


def _prev_trading_day(dt_str: str, index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    """Find the trading day strictly before the entry date."""
    entry_date = pd.Timestamp(dt_str[:10])
    prior = index[index < entry_date]
    return prior[-1] if len(prior) > 0 else None


def backfill_vix(
    trades: list[dict], vix_series: pd.Series,
) -> list[dict]:
    """Fill missing vix_at_entry using VIX close on entry_date - 1 trading day.

    Preserves existing non-None values. Mutates and returns trades list.
    """
    for t in trades:
        if t["vix_at_entry"] is not None:
            continue
        prev_day = _prev_trading_day(t["actual_entry_time"], vix_series.index)
        if prev_day is not None and prev_day in vix_series.index:
            t["vix_at_entry"] = float(vix_series.loc[prev_day])
    return trades


def crosscheck_vix(
    trades: list[dict], vix_series: pd.Series,
    threshold: float = 0.5,
) -> list[dict]:
    """Flag trades where stored vix_at_entry differs from yfinance by >threshold.

    Returns list of dicts with trade_id, stored, expected, diff.
    """
    flags = []
    for t in trades:
        if t["vix_at_entry"] is None:
            continue
        prev_day = _prev_trading_day(t["actual_entry_time"], vix_series.index)
        if prev_day is None or prev_day not in vix_series.index:
            continue
        expected = float(vix_series.loc[prev_day])
        diff = abs(t["vix_at_entry"] - expected)
        if diff > threshold:
            flags.append({
                "trade_id": t["trade_id"],
                "stored": t["vix_at_entry"],
                "expected": expected,
                "diff": round(diff, 2),
            })
    return flags


def collapse_sector(sector: str) -> str:
    """Collapse GICS sector to 4-bucket scheme."""
    return SECTOR_MAP.get(sector, "Cyclical")


def entry_hour_bucket(entry_time: str) -> str:
    """Parse ISO timestamp and return intraday hour bucket."""
    dt = datetime.fromisoformat(entry_time)
    hour = dt.hour
    minute = dt.minute
    t = hour * 60 + minute  # minutes since midnight
    if t < 630:  # before 10:30
        return "09:30-10:30"
    if t < 720:  # before 12:00
        return "10:30-12:00"
    if t < 840:  # before 14:00
        return "12:00-14:00"
    return "14:00-16:00"


def holding_period_bucket(duration_days: int) -> str:
    """Categorize holding period into short/medium/long."""
    if duration_days <= 3:
        return "short"
    if duration_days <= 6:
        return "medium"
    return "long"


def build_analysis_df(
    db_path: str, *, exclude_quarantined: bool = False,
) -> tuple[pd.DataFrame, list[dict]]:
    """Build the complete analysis DataFrame with all dimensions.

    Returns (df, vix_flags) where vix_flags lists cross-check discrepancies.
    """
    trades = load_closed_trades(db_path, exclude_quarantined=exclude_quarantined)
    vix_series = fetch_vix_daily()

    vix_flags = crosscheck_vix(trades, vix_series)
    trades = backfill_vix(trades, vix_series)

    df = pd.DataFrame(trades)
    df["entry_date"] = df["actual_entry_time"].str[:10]
    df["sector_bucket"] = df["realized_sector"].apply(collapse_sector)
    df["hour_bucket"] = df["actual_entry_time"].apply(entry_hour_bucket)
    df["duration_bucket"] = df["duration_days"].apply(holding_period_bucket)

    return df, vix_flags
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py::test_vix_backfill_no_nulls tests/diagnostics/test_regime_diagnostic.py::test_vix_crosscheck_flags_discrepancy tests/diagnostics/test_regime_diagnostic.py::test_sector_collapse_maps_all_gics tests/diagnostics/test_regime_diagnostic.py::test_entry_hour_bucket_handles_timezone tests/diagnostics/test_regime_diagnostic.py::test_holding_period_bucket_edge_cases -v
```

Expected: 5 PASSED

- [ ] **Step 7: Commit**

```bash
git checkout -b feat/regime-diagnostic-v1
git add src/diagnostics/__init__.py src/diagnostics/dimensions.py src/diagnostics/known_events.py tests/diagnostics/__init__.py tests/diagnostics/test_regime_diagnostic.py
git commit -m "feat(diagnostics): dimensions + VIX backfill + known events (D-v1 commit 1)"
```

---

## Task 2: Bootstrap + FDR + Power + Tests

**Files:**
- Create: `src/diagnostics/bootstrap.py`
- Create: `src/diagnostics/fdr.py`
- Create: `src/diagnostics/power.py`
- Modify: `tests/diagnostics/test_regime_diagnostic.py` (add tests 6-11)

### Step-by-step

- [ ] **Step 1: Write failing tests 6-11**

Append to `tests/diagnostics/test_regime_diagnostic.py`:
```python
# ── bootstrap tests ───────────────────────────────────────────────


def test_bootstrap_ci_coverage():
    """Bootstrap CI from N(0,1) should contain 0 ~95% of the time."""
    from src.diagnostics.bootstrap import bootstrap_ci

    rng = np.random.default_rng(42)
    contains_zero = 0
    trials = 200  # enough to detect gross miscalibration
    for _ in range(trials):
        data = rng.normal(0, 1, size=30)
        result = bootstrap_ci(data, n_resamples=2000, seed=None)
        if result["ci_lower"] <= 0 <= result["ci_upper"]:
            contains_zero += 1
    coverage = contains_zero / trials
    # 95% CI: expect coverage in [0.90, 1.00] with some slack
    assert 0.88 <= coverage <= 1.00, f"Coverage {coverage:.2f} outside [0.88, 1.00]"


def test_bootstrap_ci_shifted_excludes_zero():
    """Bootstrap CI from N(2, 0.5) with n=50 should NOT contain 0."""
    from src.diagnostics.bootstrap import bootstrap_ci

    rng = np.random.default_rng(42)
    data = rng.normal(2.0, 0.5, size=50)
    result = bootstrap_ci(data, n_resamples=10000, seed=42)
    assert result["ci_lower"] > 0, f"CI lower {result['ci_lower']:.3f} should be > 0"


# ── fdr tests ─────────────────────────────────────────────────────


def test_fdr_uniform_pvalues():
    """~10% of uniform p-values should survive BH at q=0.10."""
    from src.diagnostics.fdr import benjamini_hochberg

    rng = np.random.default_rng(42)
    pvals = rng.uniform(0, 1, size=100)
    adjusted, survived = benjamini_hochberg(pvals, q=0.10)
    # Under null, expect ~10 survivals, allow [2, 20]
    n_survived = sum(survived)
    assert 2 <= n_survived <= 20, f"Survived {n_survived}, expected ~10"


def test_fdr_strong_signal_survives():
    """A very small p-value always survives FDR correction."""
    from src.diagnostics.fdr import benjamini_hochberg

    rng = np.random.default_rng(42)
    pvals = list(rng.uniform(0.3, 1.0, size=19))
    pvals.append(0.001)  # inject strong signal
    adjusted, survived = benjamini_hochberg(np.array(pvals), q=0.10)
    assert survived[-1] is True, "p=0.001 should survive FDR"


# ── power tests ───────────────────────────────────────────────────


def test_power_mde_matches_scipy():
    """MDE calculation matches scipy's TTestIndPower for known params."""
    from src.diagnostics.power import cell_mde

    # At n=20, alpha=0.05, power=0.80, the MDE for a one-sample t-test
    # is approximately effect_size = 0.656 (Cohen's d)
    # With std=1.0, MDE in raw units = 0.656
    mde = cell_mde(n=20, std=1.0, alpha=0.05, power=0.80)
    assert 0.55 <= mde <= 0.75, f"MDE {mde:.3f} outside expected range"


def test_regression_power_mde():
    """Regression slope MDE is computed in correct units."""
    from src.diagnostics.power import regression_slope_mde

    # With N=88, VIX range 19-24 (std ~1.5), excess_return std ~3.0
    # MDE should be in bps-per-VIX-point, a plausible number
    mde = regression_slope_mde(
        n=88, x_std=1.5, y_std=3.0, alpha=0.05, power=0.80,
    )
    assert mde > 0, "MDE must be positive"
    # At these parameters, MDE should be roughly 0.5-1.5%/VIX-point
    assert 0.2 <= mde <= 3.0, f"MDE {mde:.3f} outside plausible range"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py -k "bootstrap or fdr or power" -v
```

Expected: 6 FAILED (ImportError)

- [ ] **Step 3: Implement bootstrap.py**

Create `src/diagnostics/bootstrap.py`:
```python
"""Bootstrap confidence interval engine.

Computes 95% CIs via percentile bootstrap with 10,000 resamples.
Statistic: mean of the input array (used for excess-Sharpe estimation).

Called by: diagnostics.analyses
Calls: numpy
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import numpy as np


def bootstrap_ci(
    data: np.ndarray,
    n_resamples: int = 10_000,
    ci: float = 0.95,
    seed: int | None = 42,
) -> dict:
    """Compute bootstrap CI for the mean of data.

    Returns dict with keys: point_estimate, ci_lower, ci_upper, p_value.
    p_value is two-sided for H0: mean = 0.
    """
    data = np.asarray(data, dtype=float)
    n = len(data)
    rng = np.random.default_rng(seed)

    point_estimate = float(np.mean(data))

    boot_means = np.empty(n_resamples)
    for i in range(n_resamples):
        sample = rng.choice(data, size=n, replace=True)
        boot_means[i] = np.mean(sample)

    alpha = 1.0 - ci
    ci_lower = float(np.percentile(boot_means, 100 * alpha / 2))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))

    # Two-sided p-value: proportion of bootstrap means on the opposite
    # side of zero from the point estimate, times 2 (capped at 1.0)
    if point_estimate >= 0:
        p_value = float(np.mean(boot_means <= 0)) * 2
    else:
        p_value = float(np.mean(boot_means >= 0)) * 2
    p_value = min(p_value, 1.0)

    return {
        "point_estimate": point_estimate,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_value": p_value,
    }
```

- [ ] **Step 4: Implement fdr.py**

Create `src/diagnostics/fdr.py`:
```python
"""Benjamini-Hochberg FDR correction.

Called by: diagnostics.analyses
Calls: numpy
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import numpy as np


def benjamini_hochberg(
    p_values: np.ndarray, q: float = 0.10,
) -> tuple[np.ndarray, list[bool]]:
    """Apply Benjamini-Hochberg FDR correction.

    Returns (adjusted_p_values, survived) where survived[i] is True
    if the i-th test survives at FDR level q.
    """
    p_values = np.asarray(p_values, dtype=float)
    m = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = p_values[sorted_idx]

    # Adjusted p-values (step-up)
    adjusted = np.empty(m)
    adjusted[sorted_idx[-1]] = sorted_p[-1]
    for i in range(m - 2, -1, -1):
        rank = i + 1
        adj = sorted_p[i] * m / rank
        adjusted[sorted_idx[i]] = min(adj, adjusted[sorted_idx[i + 1]])
    adjusted = np.clip(adjusted, 0, 1)

    survived = [bool(adjusted[i] <= q) for i in range(m)]
    return adjusted, survived
```

- [ ] **Step 5: Implement power.py**

Create `src/diagnostics/power.py`:
```python
"""Power analysis for regime diagnostic.

Computes minimum detectable effect (MDE) at 80% power for:
- Cell-level one-sample t-tests (mean excess-Sharpe)
- Regression slope (excess_return ~ vix_at_entry)

Called by: diagnostics.analyses, diagnostics.report
Calls: scipy.stats
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

from scipy import stats
import numpy as np


def cell_mde(
    n: int,
    std: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Minimum detectable effect for a one-sample t-test on the mean.

    Returns MDE in the same units as std (e.g., percent if std is in percent).
    Uses the non-central t-distribution.
    """
    if n < 2:
        return float("inf")
    df = n - 1
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    # Non-centrality parameter for desired power
    # P(T > t_crit | ncp) = power  =>  ncp = t_crit + z_power * ...
    # Approximation: ncp ≈ t_crit + z_beta where z_beta = ppf(power)
    z_beta = stats.norm.ppf(power)
    ncp = t_crit + z_beta
    # MDE = ncp * std / sqrt(n)
    mde = ncp * std / np.sqrt(n)
    return float(mde)


def regression_slope_mde(
    n: int,
    x_std: float,
    y_std: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Minimum detectable slope for simple OLS regression.

    Returns MDE in units of y per unit of x (e.g., % excess return per
    VIX point). Assumes residual std ≈ y_std (conservative; true residual
    std is lower if there's a real relationship).

    Formula: MDE_slope = t_crit_eff * y_std / (x_std * sqrt(n - 2))
    where t_crit_eff accounts for desired power.
    """
    if n < 3:
        return float("inf")
    df = n - 2
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    z_beta = stats.norm.ppf(power)
    ncp = t_crit + z_beta
    se_slope = y_std / (x_std * np.sqrt(n - 2))
    return float(ncp * se_slope)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py -v
```

Expected: 11 PASSED (5 from Task 1 + 6 new)

- [ ] **Step 7: Commit**

```bash
git add src/diagnostics/bootstrap.py src/diagnostics/fdr.py src/diagnostics/power.py tests/diagnostics/test_regime_diagnostic.py
git commit -m "feat(diagnostics): bootstrap CI + FDR + power analysis (D-v1 commit 2)"
```

---

## Task 3: Analyses (A1-A5) + Tests

**Files:**
- Create: `src/diagnostics/analyses.py`
- Modify: `tests/diagnostics/test_regime_diagnostic.py` (add tests 12-14)

### Step-by-step

- [ ] **Step 1: Write failing tests 12-14**

Append to `tests/diagnostics/test_regime_diagnostic.py`:
```python
# ── analyses tests ────────────────────────────────────────────────


def test_cells_with_insufficient_data():
    """Cells with n < 5 produce no computed stats."""
    from src.diagnostics.analyses import _cell_stats

    data = np.array([1.0, 2.0, 3.0])  # n=3 < 5
    result = _cell_stats(data, label="tiny_cell")
    assert result["n"] == 3
    assert result["status"] == "insufficient_data"
    assert result["point_estimate"] is None
    assert result["ci_lower"] is None
    assert result["p_value"] is None


def test_cells_with_sufficient_data():
    """Cells with n >= 5 produce full stats."""
    from src.diagnostics.analyses import _cell_stats

    rng = np.random.default_rng(42)
    data = rng.normal(1.0, 2.0, size=20)
    result = _cell_stats(data, label="good_cell")
    assert result["n"] == 20
    assert result["status"] == "computed"
    assert result["point_estimate"] is not None
    assert result["ci_lower"] is not None
    assert result["ci_upper"] is not None
    assert result["p_value"] is not None
    assert result["ci_lower"] <= result["point_estimate"] <= result["ci_upper"]


def test_vix_regression_returns_required_fields():
    """VIX regression result has all required fields including slope MDE."""
    from src.diagnostics.analyses import vix_regression

    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "vix_at_entry": rng.uniform(19, 25, size=50),
        "excess_return": rng.normal(0, 3, size=50),
    })
    result = vix_regression(df)
    required = ["r", "p_value", "slope", "slope_ci_lower", "slope_ci_upper",
                "intercept", "mde_slope", "mde_benchmark", "is_underpowered"]
    for key in required:
        assert key in result, f"Missing key: {key}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py -k "cells_with or vix_regression" -v
```

Expected: 3 FAILED

- [ ] **Step 3: Implement analyses.py**

Create `src/diagnostics/analyses.py`:
```python
"""Five diagnostic analyses for regime diagnostic v1.

A1: Continuous VIX regression (excess_return ~ vix_at_entry)
A2: Trade-day clustering (per-calendar-day + contiguous-run detection)
A3: Sector rotation (4-bucket stratification)
A4: Entry time-of-day (4-bucket stratification)
A5: Holding period outcomes (3-bucket stratification)

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: diagnostics.bootstrap, diagnostics.fdr, diagnostics.power,
       diagnostics.known_events
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from src.diagnostics.bootstrap import bootstrap_ci
from src.diagnostics.fdr import benjamini_hochberg
from src.diagnostics.known_events import KNOWN_EVENTS, EVENT_CATEGORIES
from src.diagnostics.power import cell_mde, regression_slope_mde

MIN_CELL_SIZE = 5
MDE_BENCHMARK_BPS_PER_VIX = 0.3  # % per VIX point


def _cell_stats(
    data: np.ndarray,
    label: str,
    n_resamples: int = 10_000,
) -> dict:
    """Compute stats for a single stratification cell.

    Returns insufficient_data if n < MIN_CELL_SIZE.
    """
    data = np.asarray(data, dtype=float)
    n = len(data)
    result = {"label": label, "n": n}

    if n < MIN_CELL_SIZE:
        result["status"] = "insufficient_data"
        result["point_estimate"] = None
        result["ci_lower"] = None
        result["ci_upper"] = None
        result["p_value"] = None
        result["mde"] = None
        return result

    boot = bootstrap_ci(data, n_resamples=n_resamples)
    std = float(np.std(data, ddof=1))
    mde = cell_mde(n=n, std=std)

    result["status"] = "computed"
    result["point_estimate"] = boot["point_estimate"]
    result["ci_lower"] = boot["ci_lower"]
    result["ci_upper"] = boot["ci_upper"]
    result["p_value"] = boot["p_value"]
    result["std"] = std
    result["mde"] = mde
    result["is_underpowered"] = mde > 0.5  # excess-Sharpe units
    return result


def _stratified_analysis(
    df: pd.DataFrame,
    group_col: str,
    value_col: str = "excess_return",
    n_resamples: int = 10_000,
) -> dict:
    """Run cell-level analysis for a stratification dimension."""
    cells = []
    p_values = []
    for label, group in sorted(df.groupby(group_col)):
        cell = _cell_stats(
            group[value_col].values, label=str(label),
            n_resamples=n_resamples,
        )
        cells.append(cell)
        if cell["p_value"] is not None:
            p_values.append(cell["p_value"])

    # FDR correction across computed cells
    if len(p_values) >= 2:
        adjusted, survived = benjamini_hochberg(
            np.array(p_values), q=0.10,
        )
        idx = 0
        for cell in cells:
            if cell["p_value"] is not None:
                cell["p_adjusted"] = float(adjusted[idx])
                cell["survives_fdr"] = survived[idx]
                idx += 1
    elif len(p_values) == 1:
        cells_with_p = [c for c in cells if c["p_value"] is not None]
        cells_with_p[0]["p_adjusted"] = cells_with_p[0]["p_value"]
        cells_with_p[0]["survives_fdr"] = cells_with_p[0]["p_value"] <= 0.10

    return {"cells": cells, "n_computed": len(p_values)}


def vix_regression(
    df: pd.DataFrame, n_resamples: int = 10_000,
) -> dict:
    """A1: OLS regression of excess_return on vix_at_entry."""
    valid = df.dropna(subset=["vix_at_entry", "excess_return"])
    x = valid["vix_at_entry"].values
    y = valid["excess_return"].values
    n = len(x)

    if n < MIN_CELL_SIZE:
        return {"status": "insufficient_data", "n": n}

    slope, intercept, r, p_value, se = stats.linregress(x, y)

    # Bootstrap CI on slope
    rng = np.random.default_rng(42)
    boot_slopes = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.choice(n, size=n, replace=True)
        s, _, _, _, _ = stats.linregress(x[idx], y[idx])
        boot_slopes[i] = s
    slope_ci_lower = float(np.percentile(boot_slopes, 2.5))
    slope_ci_upper = float(np.percentile(boot_slopes, 97.5))

    # Power analysis for slope
    x_std = float(np.std(x, ddof=1))
    y_std = float(np.std(y, ddof=1))
    mde = regression_slope_mde(n=n, x_std=x_std, y_std=y_std)

    return {
        "status": "computed",
        "n": n,
        "r": float(r),
        "r_squared": float(r ** 2),
        "slope": float(slope),
        "intercept": float(intercept),
        "p_value": float(p_value),
        "se": float(se),
        "slope_ci_lower": slope_ci_lower,
        "slope_ci_upper": slope_ci_upper,
        "mde_slope": mde,
        "mde_benchmark": MDE_BENCHMARK_BPS_PER_VIX,
        "is_underpowered": mde > MDE_BENCHMARK_BPS_PER_VIX,
        "vix_range": (float(np.min(x)), float(np.max(x))),
        "vix_std": x_std,
    }


def day_clustering(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A2: Per-calendar-day analysis + contiguous-run detection."""
    # Primary: per-day stats
    per_day = _stratified_analysis(df, "entry_date", n_resamples=n_resamples)

    # Secondary: detect contiguous 2-3 day runs with mean excess < -1%
    day_means = []
    for label, group in sorted(df.groupby("entry_date")):
        day_means.append({
            "date": str(label),
            "n": len(group),
            "mean_excess": float(group["excess_return"].mean()),
        })

    bad_runs = []
    for i in range(len(day_means)):
        for run_len in (2, 3):
            if i + run_len > len(day_means):
                break
            run = day_means[i : i + run_len]
            total_n = sum(d["n"] for d in run)
            if total_n < MIN_CELL_SIZE:
                continue
            combined_excess = []
            for d in run:
                date_trades = df[df["entry_date"] == d["date"]]
                combined_excess.extend(date_trades["excess_return"].tolist())
            run_mean = float(np.mean(combined_excess))
            if run_mean < -1.0:
                dates = [d["date"] for d in run]
                # Tertiary: match to known events
                events = []
                for d in dates:
                    if d in KNOWN_EVENTS:
                        evt = KNOWN_EVENTS[d]
                        cat = EVENT_CATEGORIES.get(evt, "Unknown")
                        events.append({"date": d, "event": evt, "category": cat})
                bad_runs.append({
                    "dates": dates,
                    "n": total_n,
                    "mean_excess": run_mean,
                    "events": events,
                    "has_repeatable_category": len(events) > 0,
                })

    return {
        "per_day": per_day,
        "day_means": day_means,
        "bad_runs": bad_runs,
    }


def sector_rotation(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A3: Per-sector-bucket excess-Sharpe with CI."""
    return _stratified_analysis(df, "sector_bucket", n_resamples=n_resamples)


def entry_time_analysis(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A4: Per-hour-bucket excess-Sharpe with CI."""
    return _stratified_analysis(df, "hour_bucket", n_resamples=n_resamples)


def holding_period(df: pd.DataFrame, n_resamples: int = 10_000) -> dict:
    """A5: Per-holding-period-bucket excess-Sharpe with CI."""
    return _stratified_analysis(df, "duration_bucket", n_resamples=n_resamples)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py -v
```

Expected: 14 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/diagnostics/analyses.py tests/diagnostics/test_regime_diagnostic.py
git commit -m "feat(diagnostics): A1-A5 analyses with cell stats + FDR (D-v1 commit 3)"
```

---

## Task 4: Plots + Smoke Test

**Files:**
- Create: `src/diagnostics/plots.py`

### Step-by-step

- [ ] **Step 1: Implement plots.py**

Create `src/diagnostics/plots.py`:
```python
"""Matplotlib plot generation for regime diagnostic v1.

Generates 6 PNG plots saved to the plot directory:
1. VIX regression scatter with CI band
2. Per-calendar-day excess return bars
3. Per-sector excess-Sharpe bars
4. Per-hour-bucket excess-Sharpe bars
5. Per-holding-period excess-Sharpe bars
6. Cumulative P&L curve with day annotations

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: matplotlib
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py (smoke test)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_vix_regression(
    df: pd.DataFrame, result: dict, plot_dir: Path,
) -> Path:
    """A1: Scatter of excess_return vs vix_at_entry with regression line."""
    fig, ax = plt.subplots(figsize=(8, 5))
    valid = df.dropna(subset=["vix_at_entry", "excess_return"])
    ax.scatter(valid["vix_at_entry"], valid["excess_return"],
               alpha=0.6, s=40, c="#3B82F6", edgecolors="white", linewidths=0.5)
    if result.get("status") == "computed":
        x_range = np.linspace(valid["vix_at_entry"].min() - 0.5,
                              valid["vix_at_entry"].max() + 0.5, 100)
        y_hat = result["slope"] * x_range + result["intercept"]
        ax.plot(x_range, y_hat, color="#EF4444", linewidth=2,
                label=f"slope={result['slope']:.3f} (p={result['p_value']:.3f})")
        ax.fill_between(x_range,
                        result["slope_ci_lower"] * x_range + result["intercept"],
                        result["slope_ci_upper"] * x_range + result["intercept"],
                        alpha=0.15, color="#EF4444")
        ax.legend(fontsize=9)
    ax.set_xlabel("VIX at Entry (prior day close)")
    ax.set_ylabel("Excess Return vs SPY (%)")
    ax.set_title("A1: Excess Return vs VIX at Entry")
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    path = plot_dir / "a1_vix_regression.png"
    _save(fig, path)
    return path


def plot_day_clustering(
    df: pd.DataFrame, result: dict, plot_dir: Path,
) -> Path:
    """A2: Per-calendar-day mean excess return bars."""
    day_means = result["day_means"]
    dates = [d["date"][5:] for d in day_means]  # MM-DD
    means = [d["mean_excess"] for d in day_means]
    ns = [d["n"] for d in day_means]
    colors = ["#EF4444" if m < -1.0 else "#3B82F6" for m in means]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(dates, means, color=colors, edgecolor="white", linewidth=0.5)
    for bar, n in zip(bars, ns):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"n={n}", ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Entry Date")
    ax.set_ylabel("Mean Excess Return (%)")
    ax.set_title("A2: Per-Day Mean Excess Return")
    plt.xticks(rotation=45, ha="right")
    path = plot_dir / "a2_day_clustering.png"
    _save(fig, path)
    return path


def plot_cumulative_pnl(df: pd.DataFrame, plot_dir: Path) -> Path:
    """A2 companion: Cumulative excess P&L curve."""
    sorted_df = df.sort_values("actual_entry_time")
    cum_excess = sorted_df["excess_return"].cumsum()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(range(len(cum_excess)), cum_excess.values,
            color="#3B82F6", linewidth=1.5)
    ax.fill_between(range(len(cum_excess)), 0, cum_excess.values,
                    alpha=0.1, color="#3B82F6")
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Trade # (chronological)")
    ax.set_ylabel("Cumulative Excess Return (%)")
    ax.set_title("Cumulative Excess Return vs SPY")
    path = plot_dir / "a2_cumulative_pnl.png"
    _save(fig, path)
    return path


def _bar_chart_with_ci(
    result: dict, title: str, filename: str, plot_dir: Path,
) -> Path:
    """Generic bar chart for stratified analyses (A3, A4, A5)."""
    cells = result["cells"]
    computed = [c for c in cells if c["status"] == "computed"]
    if not computed:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.text(0.5, 0.5, "No cells with n >= 5", ha="center",
                va="center", transform=ax.transAxes, fontsize=14)
        ax.set_title(title)
        path = plot_dir / filename
        _save(fig, path)
        return path

    labels = [c["label"] for c in computed]
    means = [c["point_estimate"] for c in computed]
    ci_low = [c["ci_lower"] for c in computed]
    ci_high = [c["ci_upper"] for c in computed]
    ns = [c["n"] for c in computed]
    errors_low = [m - l for m, l in zip(means, ci_low)]
    errors_high = [h - m for m, h in zip(means, ci_high)]

    colors = []
    for c in computed:
        if c.get("survives_fdr"):
            colors.append("#10B981")  # green: significant after FDR
        elif c["p_value"] < 0.05:
            colors.append("#F59E0B")  # amber: nominal sig, fails FDR
        else:
            colors.append("#6B7280")  # gray: not significant

    fig, ax = plt.subplots(figsize=(8, 5))
    x = range(len(labels))
    ax.bar(x, means, color=colors, edgecolor="white", linewidth=0.5)
    ax.errorbar(x, means, yerr=[errors_low, errors_high],
                fmt="none", color="black", capsize=4, linewidth=1)
    for i, n in enumerate(ns):
        y = means[i] + errors_high[i]
        ax.text(i, y, f"n={n}", ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Mean Excess Return (%) with 95% CI")
    ax.set_title(title)
    path = plot_dir / filename
    _save(fig, path)
    return path


def plot_sector(result: dict, plot_dir: Path) -> Path:
    """A3: Per-sector excess-Sharpe bars with CIs."""
    return _bar_chart_with_ci(
        result, "A3: Excess Return by Sector", "a3_sector.png", plot_dir,
    )


def plot_entry_time(result: dict, plot_dir: Path) -> Path:
    """A4: Per-hour-bucket bars with CIs."""
    return _bar_chart_with_ci(
        result, "A4: Excess Return by Entry Time", "a4_entry_time.png", plot_dir,
    )


def plot_holding_period(result: dict, plot_dir: Path) -> Path:
    """A5: Per-holding-period bars with CIs."""
    return _bar_chart_with_ci(
        result, "A5: Excess Return by Holding Period",
        "a5_holding_period.png", plot_dir,
    )
```

- [ ] **Step 2: Verify import succeeds**

```bash
cd /c/arcis/halcyon-lab && python -c "from src.diagnostics.plots import plot_vix_regression; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/diagnostics/plots.py
git commit -m "feat(diagnostics): 6 matplotlib plot generators (D-v1 commit 4)"
```

---

## Task 5: Report Generator + Integration Test

**Files:**
- Create: `src/diagnostics/report.py`
- Modify: `tests/diagnostics/test_regime_diagnostic.py` (add integration test)

### Step-by-step

- [ ] **Step 1: Write failing integration test**

Append to `tests/diagnostics/test_regime_diagnostic.py`:
```python
# ── integration tests ─────────────────────────────────────────────


def test_report_contains_all_sections():
    """Generated report has all required sections."""
    from src.diagnostics.report import generate_report

    # Build minimal synthetic results
    mock_results = {
        "n_total": 88,
        "mean_excess": -0.345,
        "aggregate_ci": {"ci_lower": -1.0, "ci_upper": 0.5, "p_value": 0.42,
                         "point_estimate": -0.345},
        "vix_flags": [],
        "a1_vix": {"status": "computed", "n": 88, "r": 0.05, "r_squared": 0.0025,
                   "slope": 0.1, "intercept": -2.0, "p_value": 0.65,
                   "se": 0.2, "slope_ci_lower": -0.3, "slope_ci_upper": 0.5,
                   "mde_slope": 1.2, "mde_benchmark": 0.3,
                   "is_underpowered": True, "vix_range": (19.2, 24.2),
                   "vix_std": 1.5},
        "a2_days": {"per_day": {"cells": [], "n_computed": 0},
                    "day_means": [], "bad_runs": []},
        "a3_sector": {"cells": [], "n_computed": 0},
        "a4_hour": {"cells": [], "n_computed": 0},
        "a5_holding": {"cells": [], "n_computed": 0},
        "decision": "UNIFORMLY_NULL",
        "decision_rationale": "No subsample shows significant excess.",
        "quarantine_note": None,
    }
    md = generate_report(mock_results, "2026-04-18")

    required_sections = [
        "# Regime Diagnostic",
        "## Executive Summary",
        "## Methodology",
        "## Aggregate Statistics",
        "## A1: VIX Regression",
        "## A2: Trade-Day Clustering",
        "## A3: Sector Rotation",
        "## A4: Entry Time-of-Day",
        "## A5: Holding Period",
        "## Power Analysis",
        "## Decision",
    ]
    for section in required_sections:
        assert section in md, f"Missing section: {section}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py::test_report_contains_all_sections -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: Implement report.py**

Create `src/diagnostics/report.py`:
```python
"""Markdown report generator for regime diagnostic v1.

Produces a structured diagnostic report with:
- Executive summary (3 paragraphs, leads with decision)
- Methodology
- Aggregate stats with bootstrap CI
- A1-A5 results tables
- Power analysis
- Decision recommendation

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations


def _fmt(v, decimals=3) -> str:
    """Format a numeric value, handling None."""
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def _cell_table(cells: list[dict]) -> str:
    """Render a list of cell results as a markdown table."""
    if not cells:
        return "*No cells to display.*\n"
    lines = [
        "| Cell | n | Mean Excess (%) | 95% CI | p-value | FDR-adj p | Survives FDR | MDE | Underpowered |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cells:
        if c["status"] == "insufficient_data":
            lines.append(
                f"| {c['label']} | {c['n']} | — | — | — | — | — | — | insufficient data |"
            )
        else:
            ci = f"[{_fmt(c['ci_lower'])}, {_fmt(c['ci_upper'])}]"
            p_adj = _fmt(c.get("p_adjusted"), 4) if c.get("p_adjusted") is not None else "—"
            fdr = "Yes" if c.get("survives_fdr") else "No"
            underpowered = "Yes" if c.get("is_underpowered") else "No"
            lines.append(
                f"| {c['label']} | {c['n']} | {_fmt(c['point_estimate'])} "
                f"| {ci} | {_fmt(c['p_value'], 4)} | {p_adj} | {fdr} "
                f"| {_fmt(c.get('mde'))} | {underpowered} |"
            )
    return "\n".join(lines) + "\n"


def generate_report(results: dict, date_str: str) -> str:
    """Generate the full markdown diagnostic report."""
    decision = results["decision"]
    rationale = results["decision_rationale"]
    agg = results["aggregate_ci"]
    a1 = results["a1_vix"]

    sections = []

    # ── Header ────────────────────────────────────────────────────
    sections.append(f"# Regime Diagnostic v1 — {date_str}\n")
    sections.append(
        f"**N = {results['n_total']}** closed trades | "
        f"**Decision: {decision}**\n"
    )

    # ── Executive Summary ─────────────────────────────────────────
    sections.append("## Executive Summary\n")
    sections.append(
        f"**Recommendation: {decision}.** {rationale}\n"
    )
    sections.append(
        f"The incumbent pullback-in-uptrend strategy produced a mean excess "
        f"return of {_fmt(results['mean_excess'])}% vs SPY across "
        f"{results['n_total']} closed trades (95% CI: "
        f"[{_fmt(agg['ci_lower'])}, {_fmt(agg['ci_upper'])}], "
        f"p = {_fmt(agg['p_value'], 4)}).\n"
    )
    if results.get("quarantine_note"):
        sections.append(f"**Quarantine note:** {results['quarantine_note']}\n")

    # ── Methodology ───────────────────────────────────────────────
    sections.append("## Methodology\n")
    sections.append(
        "- **Data source:** `shadow_trades` table (closed trades with exit and P&L)\n"
        "- **Excess return:** `pnl_pct - (spy_return_over_hold * 100)` (computed by D1 backfill)\n"
        "- **VIX:** ^VIX close on `entry_date - 1` trading day (yfinance, no look-ahead)\n"
        "- **Bootstrap:** 10,000 resamples, percentile method, 95% CI\n"
        "- **FDR:** Benjamini-Hochberg at q = 0.10\n"
        "- **Power:** Minimum detectable effect at 80% power, 5% significance\n"
        "- **Minimum cell size:** n >= 5 (cells below this are marked 'insufficient data')\n"
    )

    # ── Aggregate Statistics ──────────────────────────────────────
    sections.append("## Aggregate Statistics\n")
    sections.append(
        f"| Metric | Value |\n|---|---|\n"
        f"| N (closed trades) | {results['n_total']} |\n"
        f"| Mean excess return | {_fmt(results['mean_excess'])}% |\n"
        f"| 95% CI | [{_fmt(agg['ci_lower'])}, {_fmt(agg['ci_upper'])}] |\n"
        f"| p-value (H0: mean = 0) | {_fmt(agg['p_value'], 4)} |\n"
    )

    # ── Data Quality Notes ────────────────────────────────────────
    vix_flags = results.get("vix_flags", [])
    if vix_flags:
        sections.append("### Data Quality Notes\n")
        sections.append(
            "VIX cross-check: the following trades have `vix_at_entry` values "
            "that differ from yfinance ^VIX by more than 0.5 points:\n"
        )
        sections.append("| Trade ID | Stored | yfinance | Diff |\n|---|---|---|---|\n")
        for f in vix_flags:
            sections.append(
                f"| {f['trade_id'][:8]}... | {_fmt(f['stored'], 1)} "
                f"| {_fmt(f['expected'], 1)} | {_fmt(f['diff'], 1)} |\n"
            )

    # ── A1: VIX Regression ────────────────────────────────────────
    sections.append("## A1: VIX Regression\n")
    if a1.get("status") == "computed":
        sections.append(
            f"OLS: `excess_return = {_fmt(a1['slope'])} * vix + "
            f"{_fmt(a1['intercept'])}`\n\n"
            f"| Metric | Value |\n|---|---|\n"
            f"| r | {_fmt(a1['r'])} |\n"
            f"| r-squared | {_fmt(a1['r_squared'], 4)} |\n"
            f"| Slope | {_fmt(a1['slope'])} |\n"
            f"| Slope 95% CI | [{_fmt(a1['slope_ci_lower'])}, "
            f"{_fmt(a1['slope_ci_upper'])}] |\n"
            f"| p-value | {_fmt(a1['p_value'], 4)} |\n"
            f"| VIX range | {_fmt(a1['vix_range'][0], 1)} - "
            f"{_fmt(a1['vix_range'][1], 1)} |\n"
            f"| MDE (slope) | {_fmt(a1['mde_slope'])} %/VIX-point |\n"
            f"| Benchmark | {a1['mde_benchmark']} %/VIX-point |\n"
            f"| Underpowered? | {'Yes' if a1['is_underpowered'] else 'No'} |\n"
        )
        if a1["is_underpowered"]:
            sections.append(
                f"\n**Note:** MDE ({_fmt(a1['mde_slope'])} %/VIX-point) exceeds "
                f"benchmark ({a1['mde_benchmark']} %/VIX-point). This analysis is "
                f"underpowered — its null result should be interpreted as "
                f"'insufficient evidence', not 'no relationship'.\n"
            )
    else:
        sections.append("*Insufficient data for VIX regression.*\n")

    sections.append("\n![VIX Regression](a1_vix_regression.png)\n")

    # ── A2: Day Clustering ────────────────────────────────────────
    sections.append("## A2: Trade-Day Clustering\n")
    a2 = results["a2_days"]
    sections.append("### Per-Day Results\n")
    sections.append(_cell_table(a2["per_day"]["cells"]))
    if a2["bad_runs"]:
        sections.append("### Contiguous Bad Runs (mean excess < -1%)\n")
        for run in a2["bad_runs"]:
            dates = ", ".join(run["dates"])
            sections.append(
                f"- **{dates}** (n={run['n']}, mean excess={_fmt(run['mean_excess'])}%)"
            )
            if run["events"]:
                evts = ", ".join(f"{e['event']} ({e['category']})" for e in run["events"])
                sections.append(f"  - Matched events: {evts}")
            else:
                sections.append("  - No matched macro events")
            sections.append(
                f"  - Repeatable category: {'Yes' if run['has_repeatable_category'] else 'No'}"
            )
            sections.append("")
    else:
        sections.append("*No contiguous bad runs detected (mean excess < -1%).*\n")

    sections.append("\n![Day Clustering](a2_day_clustering.png)\n")
    sections.append("![Cumulative P&L](a2_cumulative_pnl.png)\n")

    # ── A3-A5 ─────────────────────────────────────────────────────
    for label, key, plot in [
        ("A3: Sector Rotation", "a3_sector", "a3_sector.png"),
        ("A4: Entry Time-of-Day", "a4_hour", "a4_entry_time.png"),
        ("A5: Holding Period", "a5_holding", "a5_holding_period.png"),
    ]:
        sections.append(f"## {label}\n")
        sections.append(_cell_table(results[key]["cells"]))
        sections.append(f"\n![{label}]({plot})\n")

    # ── Power Analysis ────────────────────────────────────────────
    sections.append("## Power Analysis\n")
    all_cells = []
    for key in ("a3_sector", "a4_hour", "a5_holding"):
        all_cells.extend(results[key]["cells"])
    computed_cells = [c for c in all_cells if c["status"] == "computed"]
    if computed_cells:
        sections.append(
            "| Cell | n | MDE (excess-Sharpe) | Underpowered (MDE > 0.5)? |\n"
            "|---|---|---|---|\n"
        )
        for c in computed_cells:
            up = "Yes" if c.get("is_underpowered") else "No"
            sections.append(f"| {c['label']} | {c['n']} | {_fmt(c.get('mde'))} | {up} |\n")
    sections.append(
        f"\nVIX regression MDE: {_fmt(a1.get('mde_slope'))} %/VIX-point "
        f"(benchmark: {a1.get('mde_benchmark', 0.3)} %/VIX-point, "
        f"underpowered: {'Yes' if a1.get('is_underpowered') else 'No'})\n"
    )

    # ── Decision ──────────────────────────────────────────────────
    sections.append("## Decision\n")
    sections.append(f"**{decision}**\n\n{rationale}\n")

    return "\n".join(sections)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/test_regime_diagnostic.py -v
```

Expected: 15 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/diagnostics/report.py tests/diagnostics/test_regime_diagnostic.py
git commit -m "feat(diagnostics): report generator + integration test (D-v1 commit 5)"
```

---

## Task 6: CLI Script + Docs Update

**Files:**
- Create: `scripts/diagnostics/regime_diagnostic_v1.py`
- Modify: `docs/superpowers/specs/2026-04-18-regime-diagnostic-v1-design.md` (mark complete)

### Step-by-step

- [ ] **Step 1: Create scripts directory**

```bash
mkdir -p scripts/diagnostics
```

- [ ] **Step 2: Implement the CLI script**

Create `scripts/diagnostics/regime_diagnostic_v1.py`:
```python
"""Regime Diagnostic v1 — CLI entry point.

Runs the full diagnostic pipeline: load trades, backfill VIX,
compute dimensions, run A1-A5 analyses, generate plots and report.

Usage:
    python scripts/diagnostics/regime_diagnostic_v1.py
    python scripts/diagnostics/regime_diagnostic_v1.py --exclude-quarantined
    python scripts/diagnostics/regime_diagnostic_v1.py --bootstrap-n 5000
    python scripts/diagnostics/regime_diagnostic_v1.py --db /path/to/db.sqlite3

Called by: operator (CLI)
Calls: src.diagnostics.*
Owns tables: none (read-only)
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

import numpy as np

from src.diagnostics.dimensions import build_analysis_df
from src.diagnostics.bootstrap import bootstrap_ci
from src.diagnostics.analyses import (
    vix_regression,
    day_clustering,
    sector_rotation,
    entry_time_analysis,
    holding_period,
)
from src.diagnostics.plots import (
    plot_vix_regression,
    plot_day_clustering,
    plot_cumulative_pnl,
    plot_sector,
    plot_entry_time,
    plot_holding_period,
)
from src.diagnostics.report import generate_report


def _decide(results: dict) -> tuple[str, str]:
    """Determine CONTAMINATED / UNIFORMLY_NULL / PENDING."""
    # Check if any cell survives FDR correction
    fdr_survivors = []
    for key in ("a3_sector", "a4_hour", "a5_holding"):
        for cell in results[key]["cells"]:
            if cell.get("survives_fdr"):
                fdr_survivors.append(cell)

    # Check day-clustering for repeatable contaminants
    repeatable_runs = [
        r for r in results["a2_days"]["bad_runs"]
        if r["has_repeatable_category"]
    ]

    # Check VIX regression
    a1 = results["a1_vix"]
    vix_promising = (
        a1.get("status") == "computed"
        and a1.get("p_value", 1.0) < 0.05
    )
    vix_underpowered = a1.get("is_underpowered", True)

    if fdr_survivors or repeatable_runs:
        parts = []
        if fdr_survivors:
            labels = [c["label"] for c in fdr_survivors]
            parts.append(
                f"Cell(s) {', '.join(labels)} survive FDR correction "
                f"(q=0.10), indicating non-uniform excess return."
            )
        if repeatable_runs:
            for run in repeatable_runs:
                events = [e["event"] for e in run["events"]]
                parts.append(
                    f"Bad run {', '.join(run['dates'])} maps to "
                    f"repeatable event(s): {', '.join(events)}."
                )
        return "CONTAMINATED", " ".join(parts)

    if vix_promising and vix_underpowered:
        return "PENDING", (
            f"VIX regression shows a nominal relationship "
            f"(p={a1['p_value']:.4f}) but the analysis is underpowered "
            f"(MDE={a1['mde_slope']:.3f} %/VIX-point exceeds benchmark "
            f"{a1['mde_benchmark']}). Re-run at N>=150 with broader "
            f"VIX range."
        )

    # Check if all cell-level tests are underpowered
    all_underpowered = True
    any_computed = False
    for key in ("a3_sector", "a4_hour", "a5_holding"):
        for cell in results[key]["cells"]:
            if cell["status"] == "computed":
                any_computed = True
                if not cell.get("is_underpowered", True):
                    all_underpowered = False

    if all_underpowered and any_computed:
        return "PENDING", (
            "All cell-level analyses are underpowered (MDE > 0.5 "
            "excess-Sharpe). Cannot distinguish between genuine null "
            "and insufficient sample size. Re-run at N>=150."
        )

    return "UNIFORMLY_NULL", (
        "No subsample cut (sector, time-of-day, day-cluster, holding "
        "period) shows excess return distinguishable from zero after "
        "FDR correction. The aggregate null is evenly distributed."
    )


def main() -> None:
    today = date.today().isoformat()
    default_db = "C:/arcis/data/ai_research_desk.sqlite3"

    parser = argparse.ArgumentParser(
        description="Regime Diagnostic v1 — strategy alpha decomposition"
    )
    parser.add_argument("--db", default=default_db, help="Path to SQLite DB")
    parser.add_argument(
        "--output",
        default=f"docs/diagnostics/regime-{today}.md",
        help="Output report path",
    )
    parser.add_argument(
        "--plot-dir",
        default=f"docs/diagnostics/regime-{today}/",
        help="Plot output directory",
    )
    parser.add_argument(
        "--bootstrap-n", type=int, default=10_000, help="Bootstrap resamples"
    )
    parser.add_argument(
        "--exclude-quarantined", action="store_true",
        help="Exclude quarantined trades from analysis",
    )
    args = parser.parse_args()

    plot_dir = Path(args.plot_dir)
    plot_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[diagnostic] Loading trades from {args.db}")
    print(f"[diagnostic] Exclude quarantined: {args.exclude_quarantined}")

    df, vix_flags = build_analysis_df(
        args.db, exclude_quarantined=args.exclude_quarantined,
    )
    n_total = len(df)
    print(f"[diagnostic] Loaded {n_total} closed trades")
    if vix_flags:
        print(f"[diagnostic] VIX cross-check: {len(vix_flags)} discrepancies")

    mean_excess = float(df["excess_return"].mean())
    aggregate_ci = bootstrap_ci(
        df["excess_return"].values, n_resamples=args.bootstrap_n,
    )

    print("[diagnostic] Running A1: VIX regression...")
    a1 = vix_regression(df, n_resamples=args.bootstrap_n)

    print("[diagnostic] Running A2: Day clustering...")
    a2 = day_clustering(df, n_resamples=args.bootstrap_n)

    print("[diagnostic] Running A3: Sector rotation...")
    a3 = sector_rotation(df, n_resamples=args.bootstrap_n)

    print("[diagnostic] Running A4: Entry time-of-day...")
    a4 = entry_time_analysis(df, n_resamples=args.bootstrap_n)

    print("[diagnostic] Running A5: Holding period...")
    a5 = holding_period(df, n_resamples=args.bootstrap_n)

    results = {
        "n_total": n_total,
        "mean_excess": mean_excess,
        "aggregate_ci": aggregate_ci,
        "vix_flags": vix_flags,
        "a1_vix": a1,
        "a2_days": a2,
        "a3_sector": a3,
        "a4_hour": a4,
        "a5_holding": a5,
    }

    # Quarantine sensitivity note
    if not args.exclude_quarantined:
        q_count = int(df["quarantined"].sum()) if "quarantined" in df.columns else 0
        if q_count > 0:
            results["quarantine_note"] = (
                f"{q_count} of {n_total} trades are quarantined (April 10 "
                f"cascade). Re-run with --exclude-quarantined for sensitivity."
            )
    else:
        results["quarantine_note"] = (
            "Analysis excludes quarantined trades per --exclude-quarantined flag."
        )

    decision, rationale = _decide(results)
    results["decision"] = decision
    results["decision_rationale"] = rationale

    print(f"[diagnostic] Decision: {decision}")
    print(f"[diagnostic] Generating plots...")

    plot_vix_regression(df, a1, plot_dir)
    plot_day_clustering(df, a2, plot_dir)
    plot_cumulative_pnl(df, plot_dir)
    plot_sector(a3, plot_dir)
    plot_entry_time(a4, plot_dir)
    plot_holding_period(a5, plot_dir)

    print(f"[diagnostic] Generating report...")
    md = generate_report(results, today)
    output_path.write_text(md, encoding="utf-8")

    print(f"[diagnostic] Report: {output_path}")
    print(f"[diagnostic] Plots:  {plot_dir}")
    print(f"[diagnostic] Decision: {decision}")
    print(f"\n{'='*60}")
    print(f"DECISION: {decision}")
    print(f"{'='*60}")
    print(f"{rationale}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run full test suite to verify no regressions**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/diagnostics/ -v
```

Expected: 15 PASSED

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: No new failures beyond pre-existing

- [ ] **Step 4: Run guardrail checks**

```bash
cd /c/arcis/halcyon-lab && python -m pytest tests/test_repo_structure.py -v -k "file_length or function_length" 2>&1 | tail -20
```

Expected: No new violations (all files under 400 lines, no functions over 60 lines)

- [ ] **Step 5: Commit**

```bash
git add scripts/diagnostics/regime_diagnostic_v1.py
git commit -m "feat(diagnostics): CLI entry point + decision engine (D-v1 commit 6)"
```

- [ ] **Step 6: Run the diagnostic on real data**

```bash
cd /c/arcis/halcyon-lab && python scripts/diagnostics/regime_diagnostic_v1.py --bootstrap-n 10000
```

Expected: Report generated at `docs/diagnostics/regime-2026-04-18.md` with CONTAMINATED, UNIFORMLY_NULL, or PENDING decision.

- [ ] **Step 7: Run with --exclude-quarantined for sensitivity**

```bash
cd /c/arcis/halcyon-lab && python scripts/diagnostics/regime_diagnostic_v1.py --exclude-quarantined --output docs/diagnostics/regime-2026-04-18-nonq.md --plot-dir docs/diagnostics/regime-2026-04-18-nonq/ --bootstrap-n 10000
```

Expected: Separate report for non-quarantined trades (N=27). Compare decision with primary.

- [ ] **Step 8: Final commit with docs and report**

```bash
git add docs/diagnostics/ docs/superpowers/specs/2026-04-18-regime-diagnostic-v1-design.md
git commit -m "docs: regime diagnostic v1 report + design spec (D-v1 commit 6 docs)"
```

---

## Post-Implementation Checklist

- [ ] All 15 tests pass: `pytest tests/diagnostics/ -v`
- [ ] No regressions: `pytest tests/ -q` shows no new failures
- [ ] No guardrail violations: all new files under 400 lines
- [ ] Frontend build unaffected: `cd frontend && npm run build`
- [ ] Report exists at `docs/diagnostics/regime-YYYY-MM-DD.md`
- [ ] Plots exist at `docs/diagnostics/regime-YYYY-MM-DD/`
- [ ] Decision is one of CONTAMINATED / UNIFORMLY_NULL / PENDING
- [ ] Push branch: `git push -u origin feat/regime-diagnostic-v1`
- [ ] Open PR with executive summary + decision in body
