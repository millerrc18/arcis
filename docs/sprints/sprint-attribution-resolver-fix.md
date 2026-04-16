# Sprint: Attribution Resolver Fix

**Depends on:** `docs/research/attribution-resolver-audit.md` — verdict Hypothesis B
**Authority:** SD#41 REVISED D2 follow-up
**Effort:** 1-2 hours + re-resolution pass on 1,600 compromised rows
**Branch:** `fix/attribution-resolver-multiindex`
**Tag on merge:** patch bump (e.g. v0.19.1 or v0.22.0 depending on release order)
**Priority:** HIGH — blocks any attribution-based claim; compromised rows contaminate training pipeline

---

## Goal

Fix `simulate_mechanical_outcome` so it handles the MultiIndex-column OHLCV
frames that `yfinance.download` returns in current versions. Re-resolve the
1,600 compromised rows. Preserve the old values under a `resolution_version`
tag for forensic comparison.

---

## Background

See `docs/research/attribution-resolver-audit.md` for the full diagnosis.

**Short form:** `bar.get("Low", ...)` returns `0` because bars are dicts
keyed by tuples (`('Low', 'AAPL')`), not strings. `0 <= stop_price` triggers
the stop-first branch on bar 1 for every trade, forcing 100% of resolved
rows to exit at `stop_price` with `outcome='loss'`.

Fingerprint confirmed on 1,600 / 1,600 resolved rows: `pnl_pct` is exactly
`(stop − entry) / entry × 100` in every case.

---

## Pre-Flight Checks

```bash
# Confirm yfinance still returns MultiIndex (the world hasn't changed under us)
python -c "
import yfinance as yf
d = yf.download('AAPL', period='5d', auto_adjust=True, progress=False)
print('columns:', d.columns.tolist())
print('is_multiindex:', hasattr(d.columns, 'get_level_values'))
"

# Confirm column count still 1600 loss / 370 pending before we start
python -c "
from src.config import DB_PATH; import sqlite3
c = sqlite3.connect(DB_PATH)
for r in c.execute('SELECT ranker_only_outcome, COUNT(*) FROM attribution_trades GROUP BY ranker_only_outcome'): print(r)
"
```

---

## Task List

### Task 1 — Add `resolution_version` column

**File:** `src/schema/registry.py`

Add a `ColumnDef` to `attribution_trades`:

```python
ColumnDef("resolution_version", "TEXT",
          description="Version tag for ranker_only_* resolution logic. "
                      "v1_multiindex_bug = pre-fix buggy resolution (stop-always-fires); "
                      "v2_fixed = post-fix correct resolution. "
                      "Added SD#41 REVISED D2 fix sprint."),
```

Migration script (one-off, run once):

```bash
python -c "
from src.config import DB_PATH; import sqlite3
c = sqlite3.connect(DB_PATH)
c.execute(\"UPDATE attribution_trades SET resolution_version='v1_multiindex_bug' WHERE ranker_only_outcome='loss' AND resolution_version IS NULL\")
c.commit()
print('Tagged compromised rows:', c.total_changes)
"
```

### Task 2 — Fix `resolve_pending_outcomes`

**File:** `src/attribution/logger.py` around line 210

Current code:
```python
data = yf.download(row["ticker"], start=..., end=..., progress=False, auto_adjust=True)
if data.empty:
    continue
ohlcv = data.reset_index().to_dict("records")
```

Replace with:
```python
data = yf.download(row["ticker"], start=..., end=..., progress=False, auto_adjust=True)
if data.empty:
    continue
# Flatten MultiIndex columns introduced by recent yfinance versions.
# Without this, bar.get("Low") returns the default 0 because the key
# is actually a tuple like ('Low', 'AAPL'). See SD#41 D2 audit.
if hasattr(data.columns, "get_level_values"):
    data.columns = data.columns.get_level_values(0)
ohlcv = data.reset_index().to_dict("records")
```

**Constraint:** `simulate_mechanical_outcome` itself is fine — don't change it. The fix belongs at the data-shape boundary, where the resolver owns the yfinance-specific conversion. This keeps the simulator pure-logic and unit-testable.

### Task 3 — Unit tests

**File:** `tests/attribution/test_resolver.py` (new; create `tests/attribution/__init__.py` too)

Minimum 3 tests:

```python
"""Tests for the resolver's OHLCV data-shape handling (SD#41 D2 fix)."""

import pandas as pd
import pytest
from unittest.mock import patch

from src.attribution.logger import simulate_mechanical_outcome, resolve_pending_outcomes


def _flat_columns_frame():
    """Pre-fix shape: flat string columns."""
    return pd.DataFrame({
        "Open":   [100, 101, 102, 103, 104],
        "High":   [102, 103, 105, 104, 105],
        "Low":    [99,  100, 101, 102, 103],
        "Close":  [101, 102, 104, 103, 104.5],
        "Volume": [1000] * 5,
    }, index=pd.date_range("2026-01-01", periods=5))


def _multiindex_frame(ticker="AAPL"):
    """Post-yfinance shape: MultiIndex columns."""
    df = _flat_columns_frame()
    df.columns = pd.MultiIndex.from_product([df.columns, [ticker]])
    return df


# ── The core regression prevention ────────────────────────────────────

def test_simulator_handles_flat_column_ohlcv():
    """Simulator produces the right outcome given correctly-shaped bars."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    # Entry 100, stop 95, target 105 — target hit on day 3 (High=105)
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=95, target_price=105,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "win"
    assert exit_price == 105
    assert days == 3


def test_simulator_returns_timeout_when_neither_breached():
    """No stop and no target hit → timeout at last close."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=80, target_price=120,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "timeout"
    assert exit_price == pytest.approx(104.5)
    assert days == 5


# ── The D2-specific bug prevention ────────────────────────────────────

def test_resolve_pending_flattens_multiindex_before_simulating(tmp_path):
    """Regression: yfinance MultiIndex columns must not slip through unflattened.

    Before the D2 fix, bar.get("Low") returned the default 0 because the
    DataFrame had tuple-keyed columns. Every trade exited at stop on day 1.
    """
    import sqlite3
    db = str(tmp_path / "resolver.db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE attribution_trades (
          attribution_id TEXT PRIMARY KEY, ticker TEXT, scan_timestamp TEXT,
          ranker_only_entry REAL, ranker_only_stop REAL, ranker_only_target REAL,
          ranker_only_outcome TEXT, ranker_only_pnl_pct REAL
        );
        INSERT INTO attribution_trades VALUES (
          'test-1', 'AAPL', '2026-01-01T10:00:00-05:00',
          100.0, 95.0, 105.0, 'pending', NULL
        );
    """)
    conn.commit(); conn.close()

    with patch("yfinance.download", return_value=_multiindex_frame("AAPL")):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome, ranker_only_pnl_pct FROM attribution_trades"
    ).fetchone()
    # Must NOT be ('loss', -5.0) — that's the bug signature.
    # With a proper flatten, target_price=105 is hit on day 3.
    assert row[0] == "win", (
        f"Got {row}; if it's ('loss', -5.0) the flatten regressed."
    )
    assert row[1] == pytest.approx(5.0)
```

### Task 4 — Re-resolution script

**File:** `scripts/reresolve_attribution.py` (new, ≤ 80 lines)

```python
"""Re-run the (fixed) resolver against the 1,600 rows tagged v1_multiindex_bug.

Writes new values into ranker_only_outcome / ranker_only_pnl_pct and sets
resolution_version = 'v2_fixed'. Preserves the old values in two new
columns for forensic comparison: ranker_only_outcome_v1, ranker_only_pnl_pct_v1.

Idempotent — re-running after first pass shows updated=0.
"""

from __future__ import annotations
import argparse
import logging
import os
import sqlite3
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.attribution.logger import resolve_pending_outcomes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def reresolve(dry_run: bool = False) -> dict:
    """Snapshot v1, set outcome back to 'pending' on v1-tagged rows, re-resolve, tag v2."""
    with sqlite3.connect(DB_PATH) as conn:
        # Add archive columns if missing
        existing = {r[1] for r in conn.execute("PRAGMA table_info(attribution_trades)")}
        for col in ("ranker_only_outcome_v1", "ranker_only_pnl_pct_v1"):
            if col not in existing:
                conn.execute(f"ALTER TABLE attribution_trades ADD COLUMN {col} TEXT")
        conn.commit()

        # Snapshot v1 values (first-run only)
        n_snap = conn.execute("""
            UPDATE attribution_trades
            SET ranker_only_outcome_v1 = ranker_only_outcome,
                ranker_only_pnl_pct_v1 = CAST(ranker_only_pnl_pct AS TEXT)
            WHERE resolution_version = 'v1_multiindex_bug'
              AND ranker_only_outcome_v1 IS NULL
        """).rowcount
        logger.info("Snapshotted v1 values on %d rows", n_snap)
        if dry_run:
            return {"snapshotted": n_snap, "reresolved": 0, "dry_run": True}

        # Reset those rows to pending so resolve_pending_outcomes picks them up
        n_reset = conn.execute("""
            UPDATE attribution_trades SET ranker_only_outcome='pending'
            WHERE resolution_version='v1_multiindex_bug'
        """).rowcount
        conn.commit()
        logger.info("Reset %d rows to pending for re-resolution", n_reset)

    # Now call the fixed resolver
    n_resolved = resolve_pending_outcomes(DB_PATH)

    # Tag the newly-resolved rows as v2_fixed
    with sqlite3.connect(DB_PATH) as conn:
        n_tagged = conn.execute("""
            UPDATE attribution_trades SET resolution_version='v2_fixed'
            WHERE resolution_version='v1_multiindex_bug'
              AND ranker_only_outcome != 'pending'
        """).rowcount
        conn.commit()

    result = {"snapshotted": n_snap, "reresolved": n_resolved, "re_tagged": n_tagged}
    logger.info("Re-resolution complete: %s", result)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    reresolve(dry_run=args.dry_run)
```

### Task 5 — Update render_sync for new columns

**File:** `src/sync/render_sync.py`

Ensure `resolution_version`, `ranker_only_outcome_v1`, and
`ranker_only_pnl_pct_v1` (all TEXT) pass through sync. These are TEXT so no
coercion change needed, but if a column allow-list exists for
`attribution_trades` in the sync config, add them.

### Task 6 — Verification

Post-re-resolution sanity checks:

```python
# The bug fingerprint should collapse from 1600 to ~0
python -c "
from src.config import DB_PATH; import sqlite3
c = sqlite3.connect(DB_PATH)
n = c.execute('''
  SELECT COUNT(*) FROM attribution_trades
  WHERE ranker_only_outcome='loss' AND resolution_version='v2_fixed'
    AND ABS(ranker_only_pnl_pct - ROUND((ranker_only_stop - ranker_only_entry)/ranker_only_entry*100, 2)) < 0.01
''').fetchone()[0]
total_loss = c.execute(\"SELECT COUNT(*) FROM attribution_trades WHERE ranker_only_outcome='loss' AND resolution_version='v2_fixed'\").fetchone()[0]
print(f'Stop-fingerprint rows: {n} / {total_loss} losses (expect low % in v2)')
"

# Outcome distribution should now have non-zero win and timeout
python -c "
from src.config import DB_PATH; import sqlite3
c = sqlite3.connect(DB_PATH)
for r in c.execute(\"SELECT ranker_only_outcome, COUNT(*) FROM attribution_trades WHERE resolution_version='v2_fixed' GROUP BY ranker_only_outcome\"):
    print(r)
"
```

Expected v2 distribution on a bull-market sample: roughly 35–50% `win`, 25–40% `loss`, 15–35% `timeout`. A distribution that's still all `loss` means the fix didn't land.

### Task 7 — Docs

- Re-open `docs/research/attribution-resolver-audit.md`, append Section 9
  with re-resolution results and a side-by-side v1-vs-v2 outcome table.
- Lift the Section 7 citation freeze: attribution claims can be cited again,
  sourced from `resolution_version='v2_fixed'` rows only.
- MASTER.md Diagnostic D2 Status: update to "CLOSED — resolver fixed, rows
  re-resolved, audit lifted".
- CHANGELOG entry for the patch release.

---

## Success Criteria

1. `simulate_mechanical_outcome` handles both flat and MultiIndex-column OHLCV
2. 3+ unit tests protect against regression
3. `attribution_trades` has `resolution_version`, old values archived in
   `ranker_only_outcome_v1` / `ranker_only_pnl_pct_v1`
4. Fingerprint count (pnl == stop-distance) drops from 1,600 to a small
   coincidental minority
5. `win` + `timeout` together > 0 (ideally > 40% of v2_fixed resolutions)
6. Audit doc Section 7 citation freeze lifted
7. MASTER.md D2 Status set to CLOSED

---

## Out-of-Scope

- Re-training the LLM on v2 attribution data (separate sprint — first confirm there IS signal)
- Reworking `simulate_mechanical_outcome` internals (the simulator itself is fine; the fix is upstream of it)
- Intraday path estimation (separate SD — the 7-day window is the same, only the data-shape bug is addressed here)
