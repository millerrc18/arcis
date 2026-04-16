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

---
---

# PART 2: Comprehensive Documentation & Roadmap Sweep

> Combined into this sprint per Ryan's request. These are docs-only tasks
> (plus frontend JSX for dashboard pages). If any doc merge conflict blocks
> the resolver fix, the resolver commits should be shipped first and the doc
> tasks cherry-picked into a follow-up commit.

---

## Goal (Part 2)

MASTER.md, dashboard roadmap page, and supporting docs are severely stale after
the forensic analysis pivot and 4 sprint merges on 2026-04-16. Update every
stale section to reflect the current system state.

---

## Current Counts (verified 2026-04-16)

Use these as the source of truth — **re-verify each via the listed command before writing:**

| Metric | Old (stale) | Current |
|---|---|---|
| Latest release | v0.17.2 | v0.21.0 (v0.18.0 + v0.19.0 + v0.21.0 all on 2026-04-16) |
| Closed trades | 18 (+ 77 quarantined) | 85 (verify: `SELECT COUNT(*) FROM shadow_trades WHERE actual_exit_time IS NOT NULL`) |
| Tests | 1,801 across 148 files | verify: `pytest --collect-only -q 2>&1 \| tail -1` |
| Python files | 225 | verify: `find src/ -name "*.py" -not -path "*__pycache__*" \| wc -l` |
| Test files | 148 | 154 (verify: `find tests/ -name "*.py" -not -path "*__pycache__*" \| wc -l`) |
| Dashboard pages | 24 | 25 (verify: `find frontend/src/pages -name "*.jsx" \| wc -l`) |
| Research docs | 91 | 106 (verify: `find docs/research -name "*.md" -o -name "*.pdf" \| wc -l`) |
| Sprint docs | 43 | 57 (verify: `find docs/sprints -name "*.md" \| wc -l`) |
| Strategy decisions | 40 | 41+ (SD#41 added) |
| Schema tables | 53 | verify via registry |

---

## Doc Sweep Task List

### Doc Task 1 — MASTER.md Section 1 (System Identity)

**Release line:** Update from v0.17.2 to:

```
**Release:** v0.21.0 (2026-04-16: earnings filter hard block SD#33; prior: v0.19.0 SPY-matched excess instrumentation SD#41 D1; v0.18.0 IB cold storage SD#41; v0.17.2 Grafana Loki + NSSM)
```

**Tech stack — Trading line:** Update to:

```
- Trading: Alpaca paper + live API (bracket orders, GTC); IB Gateway dormant
  per SD#41 (`trading.ib_enabled=false`), all code preserved for reactivation
```

---

### Doc Task 2 — MASTER.md Section 2 (Current State)

**Key Metrics table:** Update all stale values. Critical fixes:

- `Closed trades` → `85 closed (verify via shadow-status)`
- `Phase` → `1 (Diagnostic) -- paper $100K + $100 live via Alpaca. SD#41 REVISED: halt optimization, run diagnostics first.`
- All file/doc counts → current values from table above

**Deployed Components table:** Add/update:

- Earnings filter (SD#33): `LIVE — v0.21.0, hard block within 10 calendar days of earnings`
- SPY-matched excess instrumentation: `LIVE — v0.19.0, primary metric is now excess-Sharpe`
- IB integration: `DORMANT — v0.18.0, trading.ib_enabled=false, all code preserved`
- Dashboard: `LIVE — 25 pages (Trade History replaces Broker Comparison; excess-Sharpe lead panel)`
- Remove "PEAD enrichment (5 signals)" line — PEAD is dead per SD#3

**Add new subsections after Diagnostic D2 Status:**

```markdown
### Forensic Analysis Status (2026-04-16)

- **Report:** `docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf`
- **Key finding:** Per-trade Sharpe 3.38 is SPY beta during a bull run, not alpha.
  Mean excess vs SPY = +0.039% with t=0.098 over 75 matched periods.
- **Action:** SD#41 REVISED — halt Phase 1 optimization, run 3 diagnostics first.
- **Diagnostic D1 (SPY excess):** COMPLETE — v0.19.0, all 85 trades backfilled
- **Diagnostic D2 (attribution audit):** COMPLETE — Hypothesis B confirmed (yfinance MultiIndex bug), fix sprint drafted
- **Diagnostic D3 (regime/sector):** COMPLETE or IN PROGRESS (check branch status)
- **Attribution resolver fix:** THIS SPRINT — executing now
- **Stage 1 OOS validation:** NOT STARTED — gate: excess-mean > 0 at t > 1.0 over 30 trades
- **Stage 2 OOS validation:** NOT STARTED — gate: excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 trades

### Permanent Methodology Guardrails (SD#41 REVISED)

1. Every Sharpe claim must specify raw vs excess vs alpha
2. Every metric update must refresh the trade count
3. Category 2 forensics (own data) runs before Category 1 (literature) when both available
4. Attribution claims require methodology review — "100% accuracy" should trigger skepticism
```

**Known Blockers:** Update to:

```
- Attribution resolver produces garbage data (yfinance MultiIndex bug); fix IN THIS SPRINT
- Alpha vs SPY is statistically zero at N=85; Stage 1 OOS validation not started
- Regime classifier NULL on 67% of trades (D3 status: check branch)
- sector_context 100% NULL (realized_sector backfilled as temporary fix via D1)
- Database on OneDrive path risks WAL corruption (incident #181)
- UPS not yet purchased (CyberPower CP1500PFCLCD, ~$220)
```

---

### Doc Task 3 — MASTER.md Section 5 (Strategy Decisions)

**Update heading count:** "40 confirmed" → "41 confirmed"

**Add SD#41:**

```
41. SD#41 REVISED: Diagnostic-first plan (docs/research/SD-41-REVISED-diagnostic-first-plan.md).
    Forensic analysis of 85 closed trades revealed per-trade Sharpe 3.38 is SPY beta during a
    bull run (excess vs SPY = +0.039%, t=0.098). HALT Phase 1 optimization. Run 3 diagnostics:
    D1 SPY excess instrumentation (DONE v0.19.0), D2 attribution resolver audit (DONE, Hypothesis B
    — yfinance MultiIndex bug), D3 regime/sector diagnostic (check status). New IB gate:
    excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades. Fund timeline: 24-30 months (was 18-24).
    Supersedes prior SD#41 trade lifecycle synthesis. Category 2 overrides Category 1.
```

**Update SD#3:** `~~Strategy #3 = Evolved PEAD (Phase 3)~~ **ELIMINATED.** PEAD dead for large caps (Martineau 2022, Subrahmanyam 2025). Replaced by Options Volatility Desk in Phase 3-4.`

**Update SD#17:** Add: `**COMPROMISED (D2 audit 2026-04-16):** resolver produces 100% loss due to yfinance MultiIndex bug. Fix sprint executing. All attribution claims rescinded until re-resolution.`

**Update SD#36:** Add: `**REDEFINED (SD#41 REVISED):** excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (was raw Sharpe-based at 50 trades). See Section 6.`

---

### Doc Task 4 — MASTER.md Section 6 (Phase Gates)

**Replace Phase 1→2 gate row:**

```
| Phase 1 -> 2 | **REDEFINED (SD#41 REVISED):** excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades, zero critical bugs, 7-day uptime, ≥90% conviction parse. Raw Sharpe gate deprecated. Attribution with FIXED resolver (≥50 paired trades). Stress test (2008/2020/2022). | 85 closed, D1/D2 done, D3 in progress, resolver fix executing, Stage 1 OOS not started | ~15% (diagnostics) |
```

**Update GRPO row:** `85 closed (approaching threshold) | Blocked on hardware + excess-Sharpe validation`

---

### Doc Task 5 — MASTER.md Section 8 (Revenue & Business)

**Timeline table:** Shift all milestones +6-12 months per SD#41 REVISED:
- Month 6 → 9-12 (Phase 1 validation)
- Month 12 → 15-18 (first external revenue)
- Month 24 → 30 (fund formation)
- Month 36 → 36-42 (fund self-sustaining)

Add note: `Timeline extended 6-12 months per SD#41 REVISED. Wyoming LLC (July 2026) is calendar-driven.`

**Future Desks intraday entry:** Add `Feasibility research in progress (docs/research/deep-research/intraday-desk-feasibility-prompt.md).`

---

### Doc Task 6 — MASTER.md Section 11 (Sprint Queue)

**Replace entire active queue** with SD#41 REVISED diagnostic-first plan (see the table in the goal section above). Move all existing DONE items to a "Completed Sprints (historical)" subsection.

Add Research Queue subsection: intraday feasibility (drafted), Connors RSI(2) (pending), options vol desk (Phase 3-4).

---

### Doc Task 7 — MASTER.md Section 12 (Reference Pointers)

Update dashboard page count (22 → 25). Remove "Broker Comparison" from page list, add "Trade History (excess-Sharpe lead panel, SD#41 D1)". Verify all page names match `frontend/src/pages/*.jsx`.

---

### Doc Task 8 — Dashboard pages: stale reference check

```bash
# Check for stale hardcoded values
grep -rn "3\.38\|Sharpe.*1\.0\|50 trades\|18 closed\|Broker Comparison" frontend/src/pages/ --include="*.jsx" | head -10

# Check for roadmap page
ls frontend/src/pages/Roadmap* 2>/dev/null
grep -rn "roadmap\|phase.*gate\|milestone" frontend/src/pages/ --include="*.jsx" | head -10
```

If stale references found, update them. If a Roadmap page exists, update for SD#41 REVISED (excess-Sharpe gates, 24-30mo timeline, diagnostic progress).

---

### Doc Task 9 — README.md + CHANGELOG.md + RELEASES.md consistency

- README version badge → v0.21.0 (or whatever the latest tag is after this sprint)
- CHANGELOG version order descending
- RELEASES has all three new versions
- No "Phase 1 gate: Sharpe 1.0" language anywhere — all references use excess-Sharpe

---

## Combined Success Criteria (Parts 1 + 2)

**Part 1 (Resolver Fix):**
1. `simulate_mechanical_outcome` handles MultiIndex OHLCV
2. 3+ unit tests protect against regression
3. `attribution_trades` has `resolution_version`, old values archived
4. Fingerprint count drops from 1,600 to minority
5. `win` + `timeout` > 0 in v2_fixed resolutions
6. Audit doc citation freeze lifted
7. MASTER.md D2 Status set to CLOSED

**Part 2 (Doc Sweep):**
8. MASTER.md reflects all merges from 2026-04-16
9. Phase gates use excess-Sharpe everywhere
10. Trade count is 85+, not 18
11. Attribution claims marked rescinded (until Part 1 re-resolves)
12. Sprint queue reflects diagnostic-first plan
13. Revenue timeline shows 24-30mo
14. Dashboard pages have no stale hardcoded metrics
15. `scripts/verify_docs.py` passes
16. `cd frontend && npm run build` succeeds

---

## Combined Commit Messages

**Part 1 commits (resolver fix):**
```
feat(schema): add resolution_version + v1 archive columns to attribution_trades
fix(attribution): flatten yfinance MultiIndex before simulate_mechanical_outcome
test(attribution): MultiIndex + flat-columns + missing-data regression tests
feat(scripts): re-resolve 1,600 compromised attribution rows (v2_fixed)
docs: lift D2 citation freeze, update MASTER.md D2 Status → CLOSED
```

**Part 2 commits (doc sweep):**
```
docs(master): update Sections 1-2 (release, metrics, forensic status, guardrails)
docs(master): update Sections 5-6 (SD#41, PEAD eliminated, phase gates redefined)
docs(master): update Sections 8+11 (revenue timeline, sprint queue)
docs(master): update Section 12 (dashboard pages, reference pointers)
feat(frontend): update dashboard pages for post-forensic state
docs: README/CHANGELOG/RELEASES consistency
```
