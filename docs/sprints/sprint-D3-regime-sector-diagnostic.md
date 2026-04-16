# Sprint D3: Regime & Sector Classifier Diagnostic (FINAL)

**Authority:** SD#41 REVISED `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
**Effort:** 1 weekend (6-8 hours CC time)
**Branch:** `feat/regime-sector-diagnostic`
**Tag on merge:** `v0.20.0`
**Priority:** CRITICAL — gates regime- and sector-based levers
**Ralph-loop status:** Pass 3 complete, grounded in actual classifier code

---

## Goal

Fix the two data-quality issues blocking regime- and sector-aware lever development:

1. **`market_regime` is NULL on 67% of trades** — even though the classifier works. Hypothesis (c) "schema-recent / scanner-omits-enrichment" is already documented in `src/features/enrichment.py` lines 8-14. Fix: ensure every scanner path attaches `market_regime` via `attach_post_scan_features`.
2. **`sector_context` is 100% NULL** — because nothing reliably populates it. Fix: backfill `realized_sector` via the GICS CSV (shared with Sprint D1) and document the TEMPORARY status.

Additionally, the real regime classifier (`src/features/regime.py:188 classify_regime`) uses labels like `BULL_LOW_VOL`, `BULL_HIGH_VOL`, `CRISIS`. The forensic report saw `GREEN`, `calm_uptrend`, `volatile_uptrend` — these are OLDER labels from a different code path. Part of this sprint is identifying which labels are canonical and ensuring consistency.

---

## Background Context for CC

**Confirmed from Pass 1 audit of the repo:**

`src/features/enrichment.py` literally documents the problem (lines 8-14):

> "Why this exists: before 2026-04-14 each scanner attached (or omitted) traffic_light and event_risk scores in its own way. The mean-reversion scanner omitted both, which caused all MR candidates to fall back to conservative defaults (0.5 traffic_light, 1.0 event_risk) AND to store market_regime=NULL in the recommendations table. Centralizing the attachment here ensures every scanner that goes through a shadow_trades insert has consistently enriched features."

So hypothesis (c) is confirmed in code comments: a fix was already being applied as of 2026-04-14. This sprint's job is to:

1. Verify `attach_post_scan_features` is called on all current scanner paths
2. Catch any scanner still bypassing it
3. Add regression tests so this never recurs
4. Backfill `realized_sector` using D1's CSV

**The actual regime classifier** (`src/features/regime.py`):
- `compute_market_regime()` — produces raw features (vix_proxy, SPY SMA proximity, etc.)
- `classify_regime(regime_data)` at line 188 — returns one of 7 labels: `BULL_LOW_VOL`, `BULL_HIGH_VOL`, `TRANSITION`, `CORRECTION`, `BEAR_EARLY`, `BEAR_ESTABLISHED`, `CRISIS`
- These are the CURRENT canonical labels

**The forensic report's labels** (`GREEN`, `calm_uptrend`, `volatile_uptrend`) come from:
- `shadow_trades.regime_at_entry` — either a legacy column or written by a different code path
- Need to verify where these labels come from (Task 1)

---

## Pre-Flight Checks

```bash
# 1. Verify classifier produces canonical labels
python -c "
from src.features.regime import compute_market_regime, classify_regime
data = {'vix_proxy': 15, 'spy_above_sma200': True, 'spy_above_sma50': True, 'regime_label': 'bull', 'spy_drawdown_from_high': 0.02, 'market_breadth_pct': 65}
print('classify_regime output:', classify_regime(data))
"

# 2. Where does 'GREEN' label come from?
grep -rn "'GREEN'\|\"GREEN\"" src/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v test

# 3. Where does regime_at_entry get written?
grep -rn "regime_at_entry" src/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v test | head -5

# 4. DB state of regime fields
python -c "
from src.config import DB_PATH
import sqlite3
conn = sqlite3.connect(DB_PATH)
print('recommendations.market_regime:')
for r in conn.execute('SELECT COALESCE(market_regime, \"NULL\") as r, COUNT(*) FROM recommendations GROUP BY market_regime').fetchall():
    print(f'  {r[0]}: {r[1]}')
print('shadow_trades.regime_at_entry:')
try:
    for r in conn.execute('SELECT COALESCE(regime_at_entry, \"NULL\") as r, COUNT(*) FROM shadow_trades GROUP BY regime_at_entry').fetchall():
        print(f'  {r[0]}: {r[1]}')
except Exception as e:
    print(f'  Column missing: {e}')
print('shadow_trades.realized_sector populated:')
try:
    print('  non-NULL:', conn.execute('SELECT COUNT(*) FROM shadow_trades WHERE realized_sector IS NOT NULL').fetchone()[0])
except Exception as e:
    print(f'  Column missing (D1 prerequisite): {e}')
"

# 5. Branch
git checkout -b feat/regime-sector-diagnostic
```

---

## Task List

### Task 1 — Identify all label sources

**Deliverable:** Document at `docs/research/regime-classifier-audit.md` Section 1.

Grep through the repo to find every place that writes `regime_at_entry`, `market_regime`, or produces regime labels. Create a table:

| Writer | Column | Label vocabulary | Notes |
|---|---|---|---|
| `src/features/regime.py:classify_regime` | (returned in feature dict) | BULL_LOW_VOL, BULL_HIGH_VOL, ... CRISIS | canonical |
| `src/journal/store.py:???` | `recommendations.market_regime` | ??? | |
| `???` | `shadow_trades.regime_at_entry` | GREEN, ??? | |

Commands to run:
```bash
grep -rn "market_regime" src/ --include="*.py" | grep -v __pycache__ | grep -v test
grep -rn "regime_at_entry" src/ --include="*.py" | grep -v __pycache__ | grep -v test
grep -rn "'GREEN'\|'RED'\|'YELLOW'" src/ --include="*.py" | grep -v __pycache__ | grep -v test
grep -rn "calm_uptrend\|volatile_uptrend" src/ --include="*.py" | grep -v __pycache__ | grep -v test
```

**Document where each label vocabulary comes from.** If `GREEN/RED/YELLOW` comes from the traffic_light system (not regime classifier), document that `shadow_trades.regime_at_entry` is actually mislabeled and should be `traffic_light_at_entry`. That's a meaningful finding.

---

### Task 2 — Find all scanner paths that could bypass enrichment

**Deliverable:** List of all scanners, each with verification that they call `attach_post_scan_features`.

Known scanners in the repo (from Pass 1 audit of `src/features/enrichment.py`):
- `services.scan_service` — primary scanner
- `services.mr_scan_service` — mean-reversion scanner (the one with the bug per enrichment.py comments)
- `scheduler.universe_scanner` — possibly

Commands to find them:
```bash
grep -rn "def scan\|class.*Scanner\|run_scan" src/ --include="*.py" | grep -v __pycache__ | grep -v test | head -10
grep -rn "attach_post_scan_features\|from src.features.enrichment" src/ --include="*.py" | grep -v __pycache__ | grep -v test
```

For each scanner found, verify that its code path calls `attach_post_scan_features` before writing recommendations to DB. If any bypass is found, that's the bug that needs fixing.

---

### Task 3 — Fix the enrichment bypass (if any)

If Task 2 found a scanner that skips enrichment, patch it to call `attach_post_scan_features` in the same place the working scanners do.

Do NOT change the logic of `attach_post_scan_features` itself. Just ensure it's called.

If no bypass is found (all scanners already call it), document that and move on — the NULL issue may be purely historical (pre-2026-04-14 trades predating the fix).

---

### Task 4 — Document hypothesis verdict

Based on Tasks 1-3, determine which hypothesis explains the 67% NULL regime:

- **(a) Intermittent classifier:** Unlikely — `compute_market_regime` runs on SPY data which is always available
- **(b) Biased labels:** Possibly, if Task 1 reveals `regime_at_entry` is from a stale code path with old vocabulary
- **(c) Schema-recent / scanner bypass:** Most likely per code comments at `enrichment.py:8-14`. Task 3 confirms whether the bypass is still live.

Write the verdict in `docs/research/regime-classifier-audit.md` Section 2 with the exact evidence.

---

### Task 5 — Sector backfill (shared with D1)

**Prerequisite:** Sprint D1 creates `data/sp100-gics-lookup.csv` and the `realized_sector` column on `shadow_trades`. Coordinate with D1 — do not duplicate work.

If D1 has already shipped: just verify `realized_sector` is populated (from the pre-flight DB query in Step 4).

If D1 hasn't shipped yet but this sprint does: create the GICS CSV following D1's Task 2 spec, then backfill via:
```python
# Inline one-liner; no separate script unless D1 already shipped scripts/backfill_spy_excess.py
import sqlite3
from src.config import DB_PATH
import csv

lookup = {row['ticker']: row['gics_sector']
          for row in csv.DictReader(open('data/sp100-gics-lookup.csv'))}

with sqlite3.connect(DB_PATH) as conn:
    rows = conn.execute("SELECT trade_id, ticker FROM shadow_trades "
                        "WHERE realized_sector IS NULL "
                        "  AND actual_exit_time IS NOT NULL").fetchall()
    for trade_id, ticker in rows:
        sector = lookup.get(ticker)
        if sector:
            conn.execute("UPDATE shadow_trades SET realized_sector = ? "
                         "WHERE trade_id = ?", (sector, trade_id))
    conn.commit()
    print(f"Backfilled {len(rows)} rows")
```

---

### Task 6 — Add regression tests

**File:** `tests/features/test_enrichment_coverage.py` (new)

Minimum tests:

```python
"""Regression tests for SD#41 D3 — ensure every scanner path enriches features."""

import pytest
from unittest.mock import MagicMock, patch


def test_main_scanner_calls_attach_post_scan_features():
    """Fail if scan_service forgets to enrich features."""
    # Import the scanner module
    from src.services import scan_service
    source = open(scan_service.__file__).read()
    assert "attach_post_scan_features" in source, (
        "scan_service must call attach_post_scan_features — "
        "see src/features/enrichment.py for rationale"
    )


def test_mr_scanner_calls_attach_post_scan_features():
    """Fail if mr_scan_service forgets to enrich (historical bug)."""
    try:
        from src.services import mr_scan_service
    except ImportError:
        pytest.skip("mr_scan_service not present")
    source = open(mr_scan_service.__file__).read()
    assert "attach_post_scan_features" in source, (
        "mr_scan_service must call attach_post_scan_features — "
        "was the source of the pre-2026-04-14 NULL regime bug"
    )


def test_classify_regime_never_returns_none():
    """classify_regime should always return a string, never None."""
    from src.features.regime import classify_regime
    # Empty dict should still produce a label (default to safest regime)
    result = classify_regime({})
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


def test_classify_regime_known_vocabulary():
    """Regime labels are from a known set."""
    from src.features.regime import classify_regime
    VALID_LABELS = {
        "BULL_LOW_VOL", "BULL_HIGH_VOL", "TRANSITION", "CORRECTION",
        "BEAR_EARLY", "BEAR_ESTABLISHED", "CRISIS",
    }
    # Test several input scenarios
    scenarios = [
        {"vix_proxy": 12, "spy_above_sma200": True, "spy_above_sma50": True,
         "regime_label": "bull", "spy_drawdown_from_high": 0.01,
         "market_breadth_pct": 70},
        {"vix_proxy": 45, "spy_above_sma200": False, "spy_above_sma50": False,
         "regime_label": "bear", "spy_drawdown_from_high": 0.25,
         "market_breadth_pct": 20},
    ]
    for data in scenarios:
        result = classify_regime(data)
        assert result in VALID_LABELS, f"Unexpected label: {result}"
```

---

### Task 7 — Write the audit doc

**File:** `docs/research/regime-classifier-audit.md`

```markdown
# Regime & Sector Classifier Audit

**Date:** 2026-__-__
**Authority:** SD#41 REVISED D3
**Trigger:** Forensic report found 67% NULL regime outperforms labeled regimes by 25+ pts

## Section 1 — Label Source Map

[Task 1 table showing every writer of market_regime / regime_at_entry
and their label vocabulary]

## Section 2 — Hypothesis Verdict

**Dominant cause of NULL regime:** [c: scanner bypass / c: schema-recent / mixed]

**Evidence:**
- [from Task 2 findings on scanner paths]
- [from Task 3 findings on bypass fix]

## Section 3 — Sector Column Status

`shadow_trades.realized_sector` is now populated for X of Y closed trades
(remaining Y-X are cases where ticker is not in S&P 100 GICS lookup,
documented in the CSV).

`recommendations.sector_context` remains 100% NULL — this is the legacy
column. It was supposed to be populated by the scanner context but the
code path has always been broken. **Recommendation: deprecate
`sector_context` in favor of `realized_sector` via the GICS lookup.**

## Section 4 — Labels Going Forward

Canonical regime vocabulary (from `src/features/regime.py:classify_regime`):
- BULL_LOW_VOL, BULL_HIGH_VOL, TRANSITION, CORRECTION,
  BEAR_EARLY, BEAR_ESTABLISHED, CRISIS

Legacy labels found but deprecated:
- GREEN, calm_uptrend, volatile_uptrend (from [source identified in Task 1])

Any lever that filters on regime should use the canonical set. Update
SD#35 (regime classifier v2) to reflect this finding.

## Section 5 — Regression Protection

3 regression tests added to prevent recurrence (see
`tests/features/test_enrichment_coverage.py`):
1. Main scanner must call attach_post_scan_features
2. MR scanner must call attach_post_scan_features
3. classify_regime never returns None / always returns canonical label
```

---

### Task 8 — Documentation + MASTER.md

**Files:**
- `CHANGELOG.md` — v0.20.0 entry
- `RELEASES.md` — release notes
- `MASTER.md` — add Diagnostic D3 status section
- `README.md` — version badge

**CHANGELOG:**
```markdown
## v0.20.0

### Diagnosed — SD#41 REVISED D3
- **Regime classifier NULL anomaly:** traced to [scanner bypass /
  schema-recent / etc] per `docs/research/regime-classifier-audit.md`
- **Label vocabulary confusion:** canonical labels are the 7-state
  set from `src/features/regime.py:classify_regime`. Legacy labels
  (GREEN, calm_uptrend) deprecated.

### Added
- `realized_sector` populated via GICS lookup for all closed trades
  (shared instrumentation with D1)
- 3 regression tests enforcing scanner→enrichment coverage

### Fixed (if Task 3 found a bypass)
- [Scanner path] now calls `attach_post_scan_features`, preventing
  future NULL regime writes

### Deferred
- Regime classifier v2 (SD#35) — vocabulary rework gated on additional
  empirical data
```

---

## Success Criteria

1. `docs/research/regime-classifier-audit.md` produced with all 5 sections
2. Task 1 label-source map complete
3. If bypass found: fix shipped and tested
4. `realized_sector` populated (in coordination with D1)
5. 4 regression tests pass
6. No existing test regressions
7. `scripts/verify_docs.py` passes
8. MASTER.md updated with D3 status

---

## Commit Messages

```
audit(regime): map every label writer and vocabulary (D3 task 1)
audit(regime): classify NULL anomaly root cause (D3 task 4)
fix(scanners): ensure every path calls attach_post_scan_features
test(features): enrichment coverage regression tests
feat(data): backfill realized_sector via GICS lookup
docs: regime-classifier-audit verdict committed (D3 task 7)
docs: v0.20.0 — D3 diagnostic complete
```

---

## Out-of-Scope

- Regime classifier rewrite (SD#35 v2, separate sprint)
- Sector classifier repair (defer; use realized_sector as reliable proxy)
- Changing canonical label vocabulary (documented gap only)
- D1's SPY excess columns (parallel sprint)
- D2's attribution resolver (parallel sprint)

---

## 3× Ralph-Loop Summary

**Pass 1 (repo audit):** Found that `src/features/enrichment.py:8-14` literally documents the bug in code comments — "the mean-reversion scanner omitted both, which caused... market_regime=NULL." Found canonical labels at `src/features/regime.py:188` are BULL_LOW_VOL etc, NOT the GREEN/calm_uptrend labels in the forensic report. Found `attach_post_scan_features` is the fix centerpiece.

**Pass 2 (spec correction):** Reframed sprint from "investigate 3 hypotheses" to "verify the already-known fix from 2026-04-14 is applied everywhere." Removed speculation about hypothesis (a) and (b) which the code comments already rule out. Added label-source map task since forensic and code use different vocabularies.

**Pass 3 (tighten):** Made D1 prerequisite explicit. Regression tests now check source code for `attach_post_scan_features` literal — simpler and more robust than mocking. Reduced task count by merging backfill into single inline operation when D1 has shipped.

**Final confidence:** HIGH. Sprint is narrow: verify known fix is applied, add coverage tests, document label vocabulary. Ready for CC.
