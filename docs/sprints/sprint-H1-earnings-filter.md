# Sprint H1: Earnings Filter — Scoring Threshold Fix (FINAL)

**Authority:** SD#33 earnings gap risk mitigation
**Effort:** 1-2 hours CC time (narrow scoring fix)
**Branch:** `feat/earnings-filter-hard-block`
**Tag on merge:** `v0.21.0`
**Priority:** HIGH — parallel to D1/D2/D3 diagnostics
**Ralph-loop status:** Pass 3 complete, grounded in actual event_risk code

---

## Goal

Ensure trades are hard-blocked when earnings are scheduled within 7 trading days — regardless of the market-wide event risk score. The earnings filter infrastructure is fully built already; the gap is that **earnings proximity ≤2 days only adds +4 to the risk score while the block threshold is 8**. If the market-wide score is <4 (typical on calm days), an earnings-imminent ticker never crosses the block threshold and slips through.

This is a narrow 1-2 hour fix, not a 4-6 hour rebuild.

---

## Background Context for CC

**Pre-existing infrastructure (confirmed via Pass 1 audit — do NOT rebuild):**

| Component | File | Role |
|---|---|---|
| Earnings calendar table | DB: `earnings_calendar` | Populated nightly |
| Nightly earnings scraper | `scripts/fetch_earnings_calendar.py` | Runs via watch loop overnight schedule |
| Earnings lookup | `src/features/earnings.py::get_next_earnings_date` | Cached table + yfinance fallback |
| Earnings signals | `src/data_enrichment/earnings_signals.py` | Feature engineering |
| Event risk score | `src/features/event_risk_score.py::compute_event_risk_score` | Combines market-wide + ticker-specific |
| Sizing multiplier | `src/features/event_risk_score.py::_sizing_multiplier_from_score` (line 175) | Maps score → 0.0 (block) or fraction |
| Risk governor hard block | `src/risk/governor.py` line 430 | "Event risk hard block: no new entries" |
| Executor hook | `src/shadow_trading/executor.py` lines 570, 1934 | Sets `earnings_adjacent` on trade record |
| Schema | `shadow_trades.earnings_adjacent` (INTEGER) | Default 0 |

**The existing flow:** `event_risk_score.compute_event_risk_score(ticker)` returns a `total_score` = market_wide_score + ticker_earnings_score. The sizing multiplier at `_sizing_multiplier_from_score` returns `0.0` only when `total_score >= block_threshold=8`. Risk governor rejects when multiplier is `0.0`.

**The bug** (from `src/features/event_risk_score.py` lines 265-275):
```python
# Earnings proximity score contribution:
if days_until <= 2:
    earnings_score = 4    # Only +4, not enough to block alone
elif days_until <= 5:
    earnings_score = 2    # +2 is even further from blocking
components["earnings_proximity"] = earnings_score
# ...
total_score = int(base.get("total_score", 0) + earnings_score)
```

With `block_threshold=8` (from `config/settings.example.yaml`), a ticker with earnings TOMORROW (earnings_score=4) won't block unless market_wide score is already ≥4. On a calm day the market score can easily be 0-2, so the block never triggers.

**Config keys** (`config/settings.example.yaml`):
```yaml
event_risk:
  enabled: true
  block_threshold: 8       # Hard block at score >= 8
  alert_threshold: 6       # Telegram alert at score >= 6
  sizing_floor: 0.25       # Minimum sizing multiplier
```

---

## Pre-Flight Checks

```bash
# 1. Read the actual scoring logic
python -c "
with open('src/features/event_risk_score.py') as f:
    content = f.read()
start = content.find('def compute_event_risk_score')
print(content[start:start+1500])
"

# 2. Verify earnings_calendar populated
python -c "
from src.config import DB_PATH
import sqlite3
conn = sqlite3.connect(DB_PATH)
try:
    n = conn.execute('SELECT COUNT(*) FROM earnings_calendar').fetchone()[0]
    upcoming = conn.execute(
        \"SELECT COUNT(*) FROM earnings_calendar WHERE earnings_date > date('now')\"
    ).fetchone()[0]
    print(f'earnings_calendar rows: {n} (upcoming: {upcoming})')
except Exception as e:
    print(f'earnings_calendar issue: {e}')
"

# 3. Check current earnings_adjacent distribution
python -c "
from src.config import DB_PATH
import sqlite3
conn = sqlite3.connect(DB_PATH)
for r in conn.execute('SELECT earnings_adjacent, COUNT(*) FROM shadow_trades GROUP BY earnings_adjacent').fetchall():
    print(f'earnings_adjacent={r[0]}: n={r[1]}')
"

# 4. Check risk governor is wired up
grep -n "event_risk_multiplier\|Event risk hard block" src/risk/governor.py | head -5

# 5. Branch
git checkout -b feat/earnings-filter-hard-block
```

---

## Task List

### Task 1 — Patch earnings scoring to force block at ≤7 trading days

**File:** `src/features/event_risk_score.py`

Modify `compute_event_risk_score` so earnings within 7 trading days force `total_score >= block_threshold` regardless of market-wide score.

Find the block around line 265-275:

```python
if next_earnings is not None:
    days_until = (next_earnings - ref).days
    if days_until <= 2:
        earnings_score = 4
    elif days_until <= 5:
        earnings_score = 2
    components["earnings_proximity"] = earnings_score
    components["earnings_days"] = days_until
    components["earnings_date"] = next_earnings.isoformat()
```

Replace with:

```python
earnings_forces_block = False
if next_earnings is not None:
    days_until = (next_earnings - ref).days
    # SD#33 / Sprint H1: earnings within ~7 trading days = hard block.
    # days_until is calendar days; 10 calendar days ≈ 7 trading days.
    if days_until <= 10:
        earnings_forces_block = True
        earnings_score = block_threshold  # guarantee hard block
    elif days_until <= 2:
        earnings_score = 4
    elif days_until <= 5:
        earnings_score = 2
    components["earnings_proximity"] = earnings_score
    components["earnings_days"] = days_until
    components["earnings_date"] = next_earnings.isoformat()
    components["earnings_forces_block"] = earnings_forces_block
else:
    components["earnings_proximity"] = 0
```

**Also update the `total_score` line** to ensure forced block respects the threshold:

```python
total_score = int(base.get("total_score", 0) + earnings_score)
if earnings_forces_block:
    total_score = max(total_score, block_threshold)
```

**Why 10 calendar days ≈ 7 trading days:** 7 trading days spans up to 10 calendar days with two weekends. Conservative approximation errs on the side of blocking slightly more trades, which is the intent of a gap-risk filter.

**Constraint:** The inelegant-looking `if days_until <= 10 ... elif days_until <= 2 ...` structure is intentional — the `<= 10` branch short-circuits before `<= 2` ever triggers. Keep the old branches in place (they still assign the descriptive `earnings_score` for components dict), but the `earnings_forces_block` flag takes precedence.

**Alternative cleaner structure** (use whichever CC judges clearer, but ensure the semantics match):

```python
earnings_score = 0
earnings_forces_block = False
if next_earnings is not None:
    days_until = (next_earnings - ref).days
    components["earnings_days"] = days_until
    components["earnings_date"] = next_earnings.isoformat()

    if days_until <= 10:
        # SD#33/H1: hard block for earnings within ~7 trading days
        earnings_forces_block = True
        earnings_score = block_threshold
    elif days_until <= 5:
        earnings_score = 2

    components["earnings_proximity"] = earnings_score
    components["earnings_forces_block"] = earnings_forces_block
else:
    components["earnings_proximity"] = 0

total_score = int(base.get("total_score", 0) + earnings_score)
if earnings_forces_block:
    total_score = max(total_score, block_threshold)
```

---

### Task 2 — Add regression tests

**File:** `tests/features/test_event_risk_earnings.py` (new; check if directory exists first — if not, create `tests/features/__init__.py`)

```python
"""Regression tests for SD#33 / H1 earnings hard-block behavior."""

import sqlite3
import tempfile
import pytest
import datetime as dt
from unittest.mock import patch, MagicMock

from src.features.event_risk_score import compute_event_risk_score


@pytest.fixture
def temp_db():
    """In-memory DB with empty earnings_calendar table."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE earnings_calendar (
            ticker TEXT, earnings_date TEXT
        )
    """)
    conn.commit()
    conn.close()
    yield db_path


def _insert_earnings(db_path, ticker, earnings_date):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO earnings_calendar VALUES (?, ?)",
                 (ticker, earnings_date))
    conn.commit()
    conn.close()


def test_earnings_tomorrow_forces_hard_block(temp_db):
    """Earnings within 2 days → total_score >= block_threshold → multiplier 0."""
    today = dt.date(2026, 4, 16)
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    _insert_earnings(temp_db, "AAPL", tomorrow)

    result = compute_event_risk_score(
        ticker="AAPL",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["total_score"] >= 8, \
        f"Expected block-threshold score, got {result['total_score']}"
    assert result["sizing_multiplier"] == 0.0, \
        f"Expected multiplier 0.0 (hard block), got {result['sizing_multiplier']}"
    assert result["components"]["earnings_forces_block"] is True


def test_earnings_in_five_trading_days_forces_block(temp_db):
    """Earnings 7 calendar days out (~5 trading days) → hard block."""
    today = dt.date(2026, 4, 16)
    earnings = (today + dt.timedelta(days=7)).isoformat()
    _insert_earnings(temp_db, "MSFT", earnings)

    result = compute_event_risk_score(
        ticker="MSFT",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["sizing_multiplier"] == 0.0


def test_earnings_fifteen_days_out_no_block(temp_db):
    """Earnings 15 days out → no hard block (normal scoring applies)."""
    today = dt.date(2026, 4, 16)
    earnings = (today + dt.timedelta(days=15)).isoformat()
    _insert_earnings(temp_db, "GOOGL", earnings)

    result = compute_event_risk_score(
        ticker="GOOGL",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    # No earnings proximity score, multiplier should be 1.0 (full sizing)
    assert result["sizing_multiplier"] == 1.0
    assert result["components"]["earnings_forces_block"] is False


def test_no_earnings_data_no_block(temp_db):
    """Ticker with no earnings_calendar row → no earnings-driven block."""
    today = dt.date(2026, 4, 16)
    # temp_db is empty for this ticker

    result = compute_event_risk_score(
        ticker="UNKNOWN",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 0, "components": {}},
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["sizing_multiplier"] == 1.0
    assert result["components"]["earnings_proximity"] == 0


def test_high_market_risk_and_distant_earnings_still_blocks(temp_db):
    """If market-wide score already >= 8, block regardless of earnings."""
    today = dt.date(2026, 4, 16)
    earnings = (today + dt.timedelta(days=30)).isoformat()
    _insert_earnings(temp_db, "JPM", earnings)

    result = compute_event_risk_score(
        ticker="JPM",
        db_path=temp_db,
        reference_date=today,
        market_risk={"total_score": 9, "components": {}},  # market already extreme
        settings={"event_risk": {"block_threshold": 8, "sizing_floor": 0.25}},
    )

    assert result["sizing_multiplier"] == 0.0  # blocked by market, not earnings
```

---

### Task 3 — Verify the full chain end-to-end

**Deliverable:** Manual trace documented in the audit notes.

After Task 1's code change, manually trace the chain to confirm blocking:

```python
# Run as a manual verification (not a committed test)
from src.features.event_risk_score import compute_event_risk_score
from src.features.event_risk_score import attach_event_risk_scores
from src.config import DB_PATH, load_config

# Pick a ticker with upcoming earnings
result = compute_event_risk_score(
    ticker="AAPL",  # or whatever has earnings within 7d per earnings_calendar
    db_path=DB_PATH,
    settings=load_config(),
)
print(f"total_score: {result['total_score']}")
print(f"multiplier: {result['sizing_multiplier']}")
print(f"components: {result['components']}")
# Expect: multiplier == 0.0 if earnings within 10 calendar days
```

Verify the risk governor correctly rejects when it sees `event_risk_multiplier=0.0`:

```bash
grep -B 2 -A 6 "Event risk hard block" src/risk/governor.py | head -20
```

Confirm the reject message fires. No code change needed in the governor — it already handles multiplier=0.

---

### Task 4 — Documentation

**Files:**
- `CHANGELOG.md` — v0.21.0 entry
- `RELEASES.md` — release notes
- `MASTER.md` — mark SD#33 as IMPLEMENTED
- `README.md` — version badge

**CHANGELOG:**
```markdown
## v0.21.0

### Fixed — SD#33 earnings filter (H1)

**The bug:** Event risk scoring capped earnings proximity at +4 on score
scale where hard-block threshold was 8. On calm market days (total_score
< 4 before earnings), an earnings-imminent ticker never crossed the
threshold. Trades within 1-2 days of earnings could slip past the filter.

**The fix:** Earnings within ~7 trading days (10 calendar days) now force
total_score to at least the block_threshold, guaranteeing a hard block
via the existing event_risk_multiplier=0 → risk governor path.

**Changes:**
- `src/features/event_risk_score.py::compute_event_risk_score` —
  added `earnings_forces_block` flag and threshold-override logic
- `tests/features/test_event_risk_earnings.py` — 5 regression tests

### Rationale
Per forensic analysis, ~80% of closed trades exited via reconciled_stale;
a non-trivial share of those likely caught an earnings surprise mid-hold.
Gap risk cannot be managed by stops, vol targeting, or exits — only by
not being in the position when earnings happens.

### Unchanged infrastructure (confirmed working)
- Nightly earnings_calendar scraper (`scripts/fetch_earnings_calendar.py`)
- Earnings lookup with yfinance fallback (`src/features/earnings.py`)
- Risk governor hard-block path (`src/risk/governor.py:430`)
- Executor earnings_adjacent flag (`src/shadow_trading/executor.py:570`)
```

---

### Task 5 — Final checklist

```bash
# Run new tests
pytest tests/features/test_event_risk_earnings.py -v 2>&1 | tail -15

# No regressions
pytest tests/ --no-cov -q 2>&1 | tail -5

# Verify earnings table still populated after nightly scraper expected to run
python -c "from src.config import DB_PATH; import sqlite3; print('upcoming earnings:', sqlite3.connect(DB_PATH).execute(\"SELECT COUNT(*) FROM earnings_calendar WHERE earnings_date > date('now')\").fetchone()[0])"

# Docs verifier
python scripts/verify_docs.py 2>&1 | tail -3

# Frontend unchanged but rebuild to be safe
cd frontend && npm run build && cd ..

git push origin feat/earnings-filter-hard-block
# Merge → tag v0.21.0
```

---

## Success Criteria

1. `src/features/event_risk_score.py` patched with earnings hard-block
2. 5 regression tests pass
3. No existing test regressions
4. Manual trace confirms: ticker with earnings in 5 days → `multiplier=0.0`
5. MASTER.md marks SD#33 as implemented
6. CHANGELOG + RELEASES entries
7. `scripts/verify_docs.py` passes

---

## Commit Messages

```
fix(event_risk): earnings within 7 trading days forces hard block (SD#33)
test(event_risk): regression tests for earnings hard-block behavior
docs: mark SD#33 earnings filter as implemented
docs: v0.21.0 release notes
```

---

## Out-of-Scope

- Building new earnings infrastructure (existing infrastructure is fine)
- Closing open positions that cross earnings mid-hold (separate SD)
- Post-earnings re-entry logic (separate design)
- Dashboard changes (the rejection will show in existing risk governor reject logs)
- Backfilling `shadow_trades.earnings_adjacent` for historical trades (nice-to-have,
  but earnings_calendar has limited historical reach and these trades are already
  closed; skip unless a later sprint requests it)

---

## 3× Ralph-Loop Summary

**Pass 1 (repo audit):** Discovered the entire earnings pipeline already exists:
- `scripts/fetch_earnings_calendar.py` (nightly)
- `src/features/earnings.py` (lookup with fallback)
- `src/data_enrichment/earnings_signals.py`
- `src/features/event_risk_score.py` (scoring)
- `src/risk/governor.py:430` (hard block path)
- `src/shadow_trading/executor.py:570, 1934` (tags earnings_adjacent)
- `shadow_trades.earnings_adjacent` column (default 0)

The original first-draft sprint would have duplicated ~400 lines of working code.

**Pass 2 (spec correction):** Identified the actual bug as a scoring scale mismatch
at `event_risk_score.py:268` where earnings proximity ≤2 days adds only +4 (of 8
threshold needed). Reduced sprint scope from 10 tasks / 4-6 hours to 5 tasks /
1-2 hours.

**Pass 3 (tighten):** Added precise before/after code snippets for the fix.
Simplified regression tests to cover 5 specific scenarios (near earnings, mid-distance,
far, none, market-already-blocked). Documented out-of-scope work clearly so CC doesn't
drift into rebuild territory.

**Final confidence:** HIGH. Narrow bug fix, well-understood, minimal blast radius.
Tests cover the essential behavior. Infrastructure that's working stays untouched.
