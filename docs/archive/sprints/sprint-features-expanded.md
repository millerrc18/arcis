# Sprint: Research-Informed Feature Build + Reliability Completion
# EXPANDED IMPLEMENTATION GUIDE — March 28, 2026

> **This sprint prompt is designed for Claude Code's full context window.**
>
> Read ALL referenced source files and research documents before writing code.
> Every function signature, SQL statement, and integration point in this document
> matches the existing codebase patterns exactly. Follow them precisely.
>
> **Pre-read (mandatory, in this order):**
> 1. `AGENTS.md` — governance, counts, system overview
> 2. `docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md`
> 3. `docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md`
> 4. `docs/research/AI_Council_Redesign__5-Agent_Strategic_Brain.md`
> 5. `docs/research/PEAD_for_SP100__The_Drift_Evolved.md`
> 6. `docs/research/REINFORCE_Plus_Plus_for_Financial_LLM_RL_on_Consumer_GPUs.md`
> 7. `docs/research/Alpha_Decay_Detection_and_Strategy_Lifecycle_Management.md`
> 8. `docs/roadmap-additions-2026-03-28.md` — confirmed strategy decisions and phase gates
> 9. `docs/audit_comprehensive_2026-03-28.md` — remaining issues not yet fixed
> 10. `src/services/scan_service.py` — the scan pipeline you'll integrate into
> 11. `src/risk/governor.py` — the risk governor you'll pass Traffic Light multiplier to
> 12. `src/council/agents.py` + `src/council/protocol.py` + `src/council/engine.py` — the council you'll redesign
> 13. `src/data_enrichment/enricher.py` — the enrichment pipeline you'll add PEAD signals to
> 14. `src/llm/packet_writer.py` — the prompt template you'll add earnings context to
> 15. `src/shadow_trading/executor.py` — where IS tracking and limit orders integrate
> 16. `src/scheduler/watch.py` — the watch loop orchestrating everything
> 17. `src/evaluation/hshs.py` — the HSHS module to wire into production
> 18. `src/evaluation/system_validator.py` — the validator that needs a dashboard page
> 19. `frontend/src/App.jsx` — routing for new pages
> 20. `frontend/src/api.js` — API client for new endpoints
>
> **Run `python -m pytest tests/ -x -q` before starting. All 1,049+ tests must pass.**
>
> **Research decisions confirmed (do NOT deviate):**
> - Strategy #2 = Mean Reversion (Phase 2, Connors RSI(2), ρ = −0.35 with pullback)
> - Strategy #3 = Evolved PEAD (Phase 3, composite earnings info system)
> - RL method = Dr. GRPO (`loss_type="dr_grpo"` in TRL `GRPOTrainer`), NOT REINFORCE++ (not in TRL)
> - Skip DPO entirely (Fin-o1 finding: inconsistent for financial reasoning)
> - Breakout signals = features within pullback adapter, NOT a separate strategy
> - PEAD enrichment = features added to pullback adapter (Phase 2), NOT a separate strategy yet
> - Traffic Light = rules-based regime overlay (3 inputs, nearly impossible to overfit)
> - Council = vote-first Modified Delphi (NeurIPS 2025: majority voting > multi-agent debate)
> - All positions protected by Alpaca server-side bracket orders

---

## PART 0: Complete Remaining Reliability Fixes (4 items from prior sprint)

### 0A. Wire `src/evaluation/hshs.py` into production

**Current state:** `hshs.py` exists with `compute_hshs()` function and tests (`tests/test_hshs.py`). It is NEVER imported by any production code — only tests.

**What to do:**

**1. Add API endpoint in `src/api/routes/system.py`:**
```python
@router.get("/health/hshs")
async def get_hshs():
    """Compute and return the Halcyon System Health Score."""
    try:
        from src.evaluation.hshs import compute_hshs
        result = compute_hshs()
        return result
    except Exception as e:
        logger.error("[API] HSHS computation failed: %s", e)
        return {"error": str(e), "hshs": 0, "dimensions": {}}
```

Also add to `src/api/cloud_app.py` for the cloud dashboard (same pattern as other cloud routes — query from Render Postgres or compute locally).

**2. Wire into CTO report in `src/evaluation/cto_report.py`:**

Find the report generation function. At the end (after all other metrics), add:
```python
# HSHS composite score
try:
    from src.evaluation.hshs import compute_hshs
    hshs = compute_hshs()
    report_lines.append(f"\n## System Health Score (HSHS)")
    report_lines.append(f"Composite: {hshs.get('hshs', 0):.1f}/100")
    for dim, score in hshs.get("dimensions", {}).items():
        report_lines.append(f"  {dim}: {score:.1f}/100")
except Exception as e:
    logger.warning("[CTO] HSHS computation failed: %s", e)
```

**3. Wire into council shared context in `src/council/protocol.py`:**

In `build_shared_context()`, after the existing VIX query block (~line 155), add:
```python
try:
    from src.evaluation.hshs import compute_hshs
    hshs = compute_hshs()
    parts.append(f"System Health Score (HSHS): {hshs.get('hshs', 0):.1f}/100")
    for dim, score in hshs.get("dimensions", {}).items():
        parts.append(f"  {dim}: {score:.1f}")
except Exception:
    pass  # HSHS is supplementary context, not critical
```

**4. Add to frontend `api.js`:**
```javascript
export async function fetchHSHS() {
  return fetchApi('/health/hshs')
}
```

### 0B. Consolidate `src/scheduler/overnight.py`

**Current state:** `overnight.py` exists in `src/scheduler/` but is only imported by `scripts/overnight_train.py`. `watch.py` implements overnight logic inline (~lines 1100-1300).

**Action: Delete `overnight.py`.** The inline implementation in `watch.py` is the production path. The script `scripts/overnight_train.py` should be updated to import from `watch.py` or deleted if unused.

```bash
rm src/scheduler/overnight.py
# Update any scripts that import from it:
grep -rn "from src.scheduler.overnight" scripts/ src/ --include="*.py"
# Fix those imports or delete the scripts.
```

### 0C. Fix `notify_retrain_report` placeholder values

**File:** `src/scheduler/watch.py`, find the `notify_retrain_report` call (in the Saturday retrain section, ~line 1144 in the post-reliability branch).

**Current (broken):**
```python
notify_retrain_report(
    model_name=model_name,
    training_examples=counts.get("total", 0),
    prev_examples=counts.get("total", 0),  # WRONG: same as total
    new_this_week=counts.get("total", 0),   # WRONG: same as total
    new_paper=0,                             # WRONG: placeholder
    ...
)
```

**Fixed:**
```python
# Compute accurate week-over-week metrics
import sqlite3
from datetime import datetime, timedelta
with sqlite3.connect("ai_research_desk.sqlite3") as _conn:
    _total = _conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
    _week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    _new_this_week = _conn.execute(
        "SELECT COUNT(*) FROM training_examples WHERE created_at > ?",
        (_week_ago,)
    ).fetchone()[0]
    _new_paper = _conn.execute(
        "SELECT COUNT(*) FROM training_examples WHERE created_at > ? AND source LIKE '%paper%'",
        (_week_ago,)
    ).fetchone()[0]

notify_retrain_report(
    model_name=model_name,
    training_examples=_total,
    prev_examples=_total - _new_this_week,
    new_this_week=_new_this_week,
    new_paper=_new_paper,
    ...
)
```

### 0D. Separate live trade monitoring

**File:** `src/shadow_trading/executor.py`, function `check_and_manage_open_trades()`.

**Current:** Live trade exits are checked inside the same loop as paper trades, gated by `if trade.get("source") == "live"`. But if paper trading is disabled (`shadow_trading.enabled: false`), the entire `check_and_manage_open_trades()` might not fire for live trades.

**Fix:** In `src/scheduler/watch.py`, in the scan cycle section where `check_and_manage_open_trades()` is called, add an INDEPENDENT check for live trades:

```python
# Always check live trades regardless of paper trading state
try:
    from src.shadow_trading.executor import check_and_manage_open_trades
    live_results = check_and_manage_open_trades(
        db_path="ai_research_desk.sqlite3",
        source_filter="live"  # NEW parameter
    )
except Exception as e:
    logger.warning("[WATCH] Live trade check failed: %s", e)
```

In `check_and_manage_open_trades()`, add the `source_filter` parameter:
```python
def check_and_manage_open_trades(
    db_path: str = "ai_research_desk.sqlite3",
    source_filter: str | None = None,  # NEW: "live", "paper", or None for all
) -> dict:
```

And in the trade query, add `WHERE source = ?` filtering when `source_filter` is provided.

---

## PART 1: Traffic Light Regime System

**Research source:** `docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md`
**Research finding:** Traffic Light is the Phase 1 MVP. Only 3 inputs = nearly impossible to overfit. Rules-based = no parameter estimation. Captures volatility, trend, and credit information independently. Estimated 15-25% drawdown reduction.

### 1A. Create `src/features/traffic_light.py`

This module follows the same pattern as `src/features/regime.py`. Study that file first.

```python
"""Traffic Light regime detection overlay.

Three-indicator system for position sizing adjustment.
Research: Quantitative_Regime_Detection_for_Halcyon_Lab.md

Indicators (each scored Green=2, Yellow=1, Red=0):
  1. VIX level: Green <20, Yellow 20-30, Red >30
  2. S&P 500 vs 200-day MA: Green (above >3%), Yellow (within 3%), Red (below)
  3. HY credit spread z-score: Green (<0.5σ), Yellow (0.5-1.5σ), Red (>1.5σ)

Total 0-6 → position sizing multiplier:
  5-6: 1.0 (full sizing)
  3-4: 0.5 (half sizing)
  0-2: 0.1 (minimal/cash)

5-day persistence filter prevents whipsaw on regime transitions.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DB_PATH = "ai_research_desk.sqlite3"

# ── Indicator thresholds (from research) ──────────────────────────
VIX_GREEN = 20.0
VIX_RED = 30.0

TREND_GREEN_PCT = 0.03   # >3% above 200-DMA
TREND_RED_PCT = 0.0      # below 200-DMA

CREDIT_GREEN_Z = 0.5     # <0.5σ above 1yr mean
CREDIT_RED_Z = 1.5       # >1.5σ above 1yr mean

# ── Score-to-multiplier mapping ───────────────────────────────────
MULTIPLIER_MAP = {
    6: 1.0, 5: 1.0,    # Risk on
    4: 0.5, 3: 0.5,    # Caution
    2: 0.1, 1: 0.1, 0: 0.1,  # Risk off
}

REGIME_LABELS = {
    6: "risk_on", 5: "risk_on",
    4: "caution", 3: "caution",
    2: "risk_off", 1: "risk_off", 0: "risk_off",
}

# ── Persistence filter state ──────────────────────────────────────
# Store in DB to survive restarts
PERSISTENCE_TABLE = """\
CREATE TABLE IF NOT EXISTS traffic_light_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_score INTEGER NOT NULL DEFAULT 5,
    current_multiplier REAL NOT NULL DEFAULT 1.0,
    pending_score INTEGER,
    pending_days INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL
)
"""

PERSISTENCE_DAYS = 5  # Must persist N days before changing


def _classify_vix(vix: float) -> tuple[str, int]:
    """Classify VIX level. Returns (signal_name, score)."""
    if vix < VIX_GREEN:
        return "green", 2
    elif vix <= VIX_RED:
        return "yellow", 1
    else:
        return "red", 0


def _classify_trend(spy_close: float, spy_sma200: float) -> tuple[str, int]:
    """Classify S&P 500 vs 200-day MA. Returns (signal_name, score)."""
    if spy_sma200 <= 0:
        return "yellow", 1  # Missing data → conservative default
    pct_above = (spy_close - spy_sma200) / spy_sma200
    if pct_above > TREND_GREEN_PCT:
        return "green", 2
    elif pct_above >= TREND_RED_PCT:
        return "yellow", 1
    else:
        return "red", 0


def _classify_credit(
    credit_spread: float,
    credit_spread_1y_mean: float,
    credit_spread_1y_std: float,
) -> tuple[str, int]:
    """Classify HY credit spread z-score. Returns (signal_name, score).

    Uses FRED series BAMLH0A0HYM2 (ICE BofA US High Yield OAS).
    z-score = (current - 1yr_mean) / 1yr_std
    """
    if credit_spread_1y_std <= 0:
        return "yellow", 1  # Missing data → conservative default
    z = (credit_spread - credit_spread_1y_mean) / credit_spread_1y_std
    if z < CREDIT_GREEN_Z:
        return "green", 2
    elif z <= CREDIT_RED_Z:
        return "yellow", 1
    else:
        return "red", 0


def _get_credit_spread_stats(db_path: str = DB_PATH) -> tuple[float, float, float]:
    """Fetch current HY credit spread and 1-year stats from macro_snapshots.

    The macro_collector stores BAMLH0A0HYM2 nightly in macro_snapshots.
    Returns (current_spread, 1yr_mean, 1yr_std).
    """
    try:
        with sqlite3.connect(db_path) as conn:
            # Most recent value
            row = conn.execute(
                "SELECT value FROM macro_snapshots "
                "WHERE series_id = 'BAMLH0A0HYM2' "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
            current = float(row[0]) if row else None

            # 1-year stats (252 trading days ≈ 1 year)
            one_year_ago = (datetime.now(ET) - timedelta(days=365)).strftime("%Y-%m-%d")
            stats = conn.execute(
                "SELECT AVG(value), "
                "       CASE WHEN COUNT(*) > 1 THEN "
                "         SQRT(SUM((value - (SELECT AVG(value) FROM macro_snapshots "
                "           WHERE series_id = 'BAMLH0A0HYM2' AND date >= ?)) * "
                "           (value - (SELECT AVG(value) FROM macro_snapshots "
                "           WHERE series_id = 'BAMLH0A0HYM2' AND date >= ?))) / "
                "           (COUNT(*) - 1)) "
                "       ELSE 1.0 END "
                "FROM macro_snapshots "
                "WHERE series_id = 'BAMLH0A0HYM2' AND date >= ?",
                (one_year_ago, one_year_ago, one_year_ago),
            ).fetchone()

            if current is None:
                logger.warning("[TRAFFIC_LIGHT] No HY credit spread data available")
                return 0.0, 0.0, 1.0  # Defaults that produce Yellow

            mean_1y = float(stats[0]) if stats and stats[0] else current
            std_1y = float(stats[1]) if stats and stats[1] and stats[1] > 0 else 1.0

            return current, mean_1y, std_1y
    except Exception as e:
        logger.warning("[TRAFFIC_LIGHT] Credit spread query failed: %s", e)
        return 0.0, 0.0, 1.0  # Defaults that produce Yellow


def _load_persistence_state(db_path: str = DB_PATH) -> dict:
    """Load the current Traffic Light state from DB."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(PERSISTENCE_TABLE)
            row = conn.execute("SELECT * FROM traffic_light_state WHERE id = 1").fetchone()
            if row:
                return {
                    "current_score": row[1],
                    "current_multiplier": row[2],
                    "pending_score": row[3],
                    "pending_days": row[4] or 0,
                    "last_updated": row[5],
                }
    except Exception as e:
        logger.warning("[TRAFFIC_LIGHT] Failed to load state: %s", e)

    # Default: risk_on
    return {
        "current_score": 5,
        "current_multiplier": 1.0,
        "pending_score": None,
        "pending_days": 0,
        "last_updated": datetime.now(ET).isoformat(),
    }


def _save_persistence_state(state: dict, db_path: str = DB_PATH) -> None:
    """Save Traffic Light state to DB."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(PERSISTENCE_TABLE)
            conn.execute(
                "INSERT OR REPLACE INTO traffic_light_state "
                "(id, current_score, current_multiplier, pending_score, pending_days, last_updated) "
                "VALUES (1, ?, ?, ?, ?, ?)",
                (
                    state["current_score"],
                    state["current_multiplier"],
                    state.get("pending_score"),
                    state.get("pending_days", 0),
                    datetime.now(ET).isoformat(),
                ),
            )
    except Exception as e:
        logger.warning("[TRAFFIC_LIGHT] Failed to save state: %s", e)


def compute_traffic_light(
    spy_data: pd.DataFrame,
    vix: float | None = None,
    db_path: str = DB_PATH,
) -> dict:
    """Compute Traffic Light regime score and position sizing multiplier.

    Args:
        spy_data: SPY OHLCV DataFrame (needs 'Close' column, 200+ rows for SMA)
        vix: Current VIX value. If None, uses vix_proxy from spy_data volatility.
        db_path: Path to SQLite database for credit spread data and persistence.

    Returns:
        {
            "vix_signal": "green"|"yellow"|"red",
            "vix_score": 0|1|2,
            "vix_value": float,
            "trend_signal": "green"|"yellow"|"red",
            "trend_score": 0|1|2,
            "spy_close": float,
            "spy_sma200": float,
            "spy_pct_above_sma200": float,
            "credit_signal": "green"|"yellow"|"red",
            "credit_score": 0|1|2,
            "credit_spread": float,
            "credit_z_score": float,
            "raw_score": 0-6,
            "total_score": 0-6,  (after persistence filter)
            "sizing_multiplier": 0.1|0.5|1.0,
            "regime_label": "risk_on"|"caution"|"risk_off",
            "persistence_days": int,
            "score_changed": bool,
            "pending_change": bool,
        }
    """
    result = {}

    # ── 1. VIX indicator ──────────────────────────────────────────
    if vix is None:
        # Estimate from SPY 20-day realized vol (annualized)
        if len(spy_data) >= 20:
            returns = spy_data["Close"].pct_change().dropna().tail(20)
            vix = float(returns.std() * np.sqrt(252) * 100)
        else:
            vix = 20.0  # Default to Yellow
            logger.warning("[TRAFFIC_LIGHT] No VIX data, defaulting to %.1f", vix)

    vix_signal, vix_score = _classify_vix(vix)
    result["vix_signal"] = vix_signal
    result["vix_score"] = vix_score
    result["vix_value"] = round(vix, 2)

    # ── 2. Trend indicator ────────────────────────────────────────
    spy_close = float(spy_data["Close"].iloc[-1])
    spy_sma200 = float(spy_data["Close"].rolling(200).mean().iloc[-1]) if len(spy_data) >= 200 else spy_close

    trend_signal, trend_score = _classify_trend(spy_close, spy_sma200)
    pct_above = (spy_close - spy_sma200) / spy_sma200 if spy_sma200 > 0 else 0.0

    result["trend_signal"] = trend_signal
    result["trend_score"] = trend_score
    result["spy_close"] = round(spy_close, 2)
    result["spy_sma200"] = round(spy_sma200, 2)
    result["spy_pct_above_sma200"] = round(pct_above * 100, 2)

    # ── 3. Credit spread indicator ────────────────────────────────
    credit_spread, credit_mean, credit_std = _get_credit_spread_stats(db_path)
    credit_signal, credit_score = _classify_credit(credit_spread, credit_mean, credit_std)
    credit_z = (credit_spread - credit_mean) / credit_std if credit_std > 0 else 0.0

    result["credit_signal"] = credit_signal
    result["credit_score"] = credit_score
    result["credit_spread"] = round(credit_spread, 4)
    result["credit_z_score"] = round(credit_z, 2)

    # ── 4. Raw score ──────────────────────────────────────────────
    raw_score = vix_score + trend_score + credit_score
    result["raw_score"] = raw_score

    # ── 5. Persistence filter ─────────────────────────────────────
    state = _load_persistence_state(db_path)
    current_score = state["current_score"]
    pending_score = state.get("pending_score")
    pending_days = state.get("pending_days", 0)

    score_changed = False
    pending_change = False

    if raw_score != current_score:
        # Score differs from current active score
        if pending_score == raw_score:
            # Same pending score — increment persistence counter
            pending_days += 1
            if pending_days >= PERSISTENCE_DAYS:
                # Persistence threshold met — adopt new score
                current_score = raw_score
                pending_score = None
                pending_days = 0
                score_changed = True
                logger.info(
                    "[TRAFFIC_LIGHT] Score changed to %d after %d days persistence",
                    current_score, PERSISTENCE_DAYS,
                )
            else:
                pending_change = True
        else:
            # New pending score — reset counter
            pending_score = raw_score
            pending_days = 1
            pending_change = True
    else:
        # Score matches current — clear any pending
        pending_score = None
        pending_days = 0

    # Save state
    _save_persistence_state({
        "current_score": current_score,
        "current_multiplier": MULTIPLIER_MAP.get(current_score, 0.5),
        "pending_score": pending_score,
        "pending_days": pending_days,
    }, db_path)

    result["total_score"] = current_score
    result["sizing_multiplier"] = MULTIPLIER_MAP.get(current_score, 0.5)
    result["regime_label"] = REGIME_LABELS.get(current_score, "caution")
    result["persistence_days"] = pending_days
    result["score_changed"] = score_changed
    result["pending_change"] = pending_change

    logger.info(
        "[TRAFFIC_LIGHT] VIX=%s(%d) Trend=%s(%d) Credit=%s(%d) "
        "Raw=%d Active=%d Mult=%.1f%s",
        vix_signal, vix_score, trend_signal, trend_score,
        credit_signal, credit_score, raw_score, current_score,
        result["sizing_multiplier"],
        f" (pending→{pending_score} day {pending_days}/{PERSISTENCE_DAYS})" if pending_change else "",
    )

    return result
```

### 1B. Wire Traffic Light into the scan pipeline

**File:** `src/services/scan_service.py`

After the data enrichment block (~line 59 in the post-reliability branch, after the `enrich_features()` call and before the `data_integrity` validation), add:

```python
    # ── Traffic Light regime overlay ──────────────────────────────
    traffic_light = {}
    try:
        from src.features.traffic_light import compute_traffic_light
        # VIX from regime data (already computed in feature engine)
        vix_value = regime.get("vix_proxy")
        traffic_light = compute_traffic_light(spy, vix=vix_value)
        logger.info(
            "[SCAN] Traffic Light: score=%d mult=%.1f regime=%s",
            traffic_light.get("total_score", -1),
            traffic_light.get("sizing_multiplier", 1.0),
            traffic_light.get("regime_label", "unknown"),
        )
    except Exception as e:
        logger.warning("[SCAN] Traffic Light computation failed: %s — using default (1.0)", e)
        traffic_light = {"sizing_multiplier": 1.0, "total_score": -1, "regime_label": "unknown"}
```

Then, when building the result dict for each packet-worthy ticker, include:
```python
    # Inside the per-ticker loop, add traffic_light to features
    features[ticker]["traffic_light"] = traffic_light
    features[ticker]["traffic_light_multiplier"] = traffic_light.get("sizing_multiplier", 1.0)
```

### 1C. Wire Traffic Light into the risk governor

**File:** `src/risk/governor.py`

Modify `check_trade()` to accept and apply the Traffic Light multiplier:

```python
    def check_trade(self, ticker: str, allocation_dollars: float,
                    features: dict, portfolio: dict,
                    traffic_light_multiplier: float = 1.0,  # NEW
                    ) -> dict:
```

At the START of the check (before any other checks), apply the multiplier:
```python
        # Traffic Light regime sizing override
        if traffic_light_multiplier < 1.0:
            original = allocation_dollars
            allocation_dollars *= traffic_light_multiplier
            checks.append({
                "name": "traffic_light",
                "passed": True,
                "detail": f"Traffic Light multiplier {traffic_light_multiplier:.1f}x: "
                          f"${original:.0f} → ${allocation_dollars:.0f}",
            })
```

**File:** `src/shadow_trading/executor.py`

In `open_shadow_trade()`, extract the multiplier from features and pass to the governor:
```python
    tl_mult = features.get("traffic_light_multiplier", 1.0)
    # ... in the governor call:
    result = governor.check_trade(
        ticker=packet.ticker,
        allocation_dollars=allocation,
        features=features,
        portfolio=portfolio,
        traffic_light_multiplier=tl_mult,  # NEW
    )
```

### 1D. Log Traffic Light to scan_metrics

**File:** `src/scheduler/watch.py`

In the `_ensure_all_tables()` method, add columns to the `scan_metrics` table:
```sql
ALTER TABLE scan_metrics ADD COLUMN traffic_light_score INTEGER DEFAULT -1;
ALTER TABLE scan_metrics ADD COLUMN traffic_light_multiplier REAL DEFAULT 1.0;
ALTER TABLE scan_metrics ADD COLUMN traffic_light_regime TEXT DEFAULT 'unknown';
```

Use the safe ALTER pattern that ignores "duplicate column name" errors:
```python
for col_sql in [
    "ALTER TABLE scan_metrics ADD COLUMN traffic_light_score INTEGER DEFAULT -1",
    "ALTER TABLE scan_metrics ADD COLUMN traffic_light_multiplier REAL DEFAULT 1.0",
    "ALTER TABLE scan_metrics ADD COLUMN traffic_light_regime TEXT DEFAULT 'unknown'",
]:
    try:
        conn.execute(col_sql)
    except sqlite3.OperationalError:
        pass  # Column already exists
```

In `_save_scan_metrics()`, include the Traffic Light values:
```python
    traffic_light_score=traffic_light.get("total_score", -1),
    traffic_light_multiplier=traffic_light.get("sizing_multiplier", 1.0),
    traffic_light_regime=traffic_light.get("regime_label", "unknown"),
```

### 1E. Telegram notification for Traffic Light

In the scan notification section of `watch.py`, include the Traffic Light status:
```python
    tl = traffic_light or {}
    tl_emoji = {"risk_on": "🟢", "caution": "🟡", "risk_off": "🔴"}.get(
        tl.get("regime_label", ""), "⚪"
    )
    # Add to scan message:
    f"{tl_emoji} Traffic Light: {tl.get('total_score', '?')}/6 (×{tl.get('sizing_multiplier', 1.0):.1f})"
```

### 1F. Dashboard widget

**File:** `frontend/src/pages/Dashboard.jsx`

Add a small Traffic Light component that shows 3 colored circles:
```jsx
function TrafficLightWidget({ data }) {
  const colors = { green: '#10B981', yellow: '#F59E0B', red: '#EF4444' };
  const signals = [
    { label: 'VIX', signal: data?.vix_signal, value: data?.vix_value },
    { label: 'Trend', signal: data?.trend_signal, value: `${data?.spy_pct_above_sma200?.toFixed(1)}%` },
    { label: 'Credit', signal: data?.credit_signal, value: `${data?.credit_z_score?.toFixed(1)}σ` },
  ];
  return (
    <div className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-lg">
      <span className="text-xs text-slate-400 font-medium">TRAFFIC LIGHT</span>
      {signals.map(s => (
        <div key={s.label} className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: colors[s.signal] || '#6B7280' }} />
          <span className="text-xs text-slate-300">{s.label}</span>
        </div>
      ))}
      <span className="text-sm font-bold text-white ml-2">
        {data?.total_score}/6 × {data?.sizing_multiplier?.toFixed(1)}
      </span>
    </div>
  );
}
```

Fetch from `/api/scan/latest` or add a dedicated endpoint. The Traffic Light data can be included in the scan results that the dashboard already fetches.

### 1G. Tests — `tests/test_traffic_light.py`

Follow the pattern in `tests/test_gate_evaluator.py` for fixtures and structure:

```python
"""Tests for src.features.traffic_light."""

import sqlite3
import numpy as np
import pandas as pd
import pytest
from src.features.traffic_light import (
    compute_traffic_light,
    _classify_vix,
    _classify_trend,
    _classify_credit,
    PERSISTENCE_DAYS,
)


@pytest.fixture
def spy_data():
    """Generate synthetic SPY data with 250 rows."""
    np.random.seed(42)
    dates = pd.date_range("2025-06-01", periods=250, freq="B")
    close = 500 + np.cumsum(np.random.randn(250) * 2)
    return pd.DataFrame({"Close": close, "Open": close, "High": close + 2, "Low": close - 2, "Volume": 1e8}, index=dates)


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database with macro_snapshots."""
    db = str(tmp_path / "test.sqlite3")
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE macro_snapshots (
            id INTEGER PRIMARY KEY, series_id TEXT, date TEXT, value REAL)""")
        # Insert 1 year of HY spread data
        for i in range(252):
            date = f"2025-{(i // 30 + 1):02d}-{(i % 28 + 1):02d}"
            conn.execute(
                "INSERT INTO macro_snapshots (series_id, date, value) VALUES (?, ?, ?)",
                ("BAMLH0A0HYM2", date, 3.5 + np.random.randn() * 0.5),
            )
    return db


class TestVIXClassifier:
    def test_green(self):
        assert _classify_vix(15.0) == ("green", 2)

    def test_yellow_low(self):
        assert _classify_vix(20.0) == ("yellow", 1)

    def test_yellow_high(self):
        assert _classify_vix(29.9) == ("yellow", 1)

    def test_red(self):
        assert _classify_vix(30.1) == ("red", 0)

    def test_extreme(self):
        assert _classify_vix(80.0) == ("red", 0)


class TestTrendClassifier:
    def test_green(self):
        # 5% above SMA200
        assert _classify_trend(105.0, 100.0) == ("green", 2)

    def test_yellow(self):
        # 1% above SMA200
        assert _classify_trend(101.0, 100.0) == ("yellow", 1)

    def test_red(self):
        # Below SMA200
        assert _classify_trend(98.0, 100.0) == ("red", 0)

    def test_missing_sma(self):
        assert _classify_trend(100.0, 0.0) == ("yellow", 1)


class TestCreditClassifier:
    def test_green(self):
        assert _classify_credit(3.5, 3.5, 1.0) == ("green", 2)  # z=0

    def test_yellow(self):
        assert _classify_credit(4.5, 3.5, 1.0) == ("yellow", 1)  # z=1.0

    def test_red(self):
        assert _classify_credit(5.5, 3.5, 1.0) == ("red", 0)  # z=2.0

    def test_missing_std(self):
        assert _classify_credit(4.0, 3.5, 0.0) == ("yellow", 1)


class TestComputeTrafficLight:
    def test_all_green(self, spy_data, tmp_db):
        """All indicators green should produce score 6, multiplier 1.0."""
        result = compute_traffic_light(spy_data, vix=15.0, db_path=tmp_db)
        assert result["raw_score"] >= 4  # At least caution (credit depends on random data)
        assert result["sizing_multiplier"] >= 0.5
        assert result["regime_label"] in ("risk_on", "caution")

    def test_all_red(self, spy_data, tmp_db):
        """High VIX should produce low score."""
        result = compute_traffic_light(spy_data, vix=45.0, db_path=tmp_db)
        assert result["vix_score"] == 0
        assert result["vix_signal"] == "red"

    def test_persistence_filter(self, spy_data, tmp_db):
        """Score should not change until persistence threshold met."""
        # First call establishes baseline
        r1 = compute_traffic_light(spy_data, vix=15.0, db_path=tmp_db)
        initial_score = r1["total_score"]

        # Subsequent calls with very different VIX should not change immediately
        for i in range(PERSISTENCE_DAYS - 1):
            r = compute_traffic_light(spy_data, vix=45.0, db_path=tmp_db)
            assert r["total_score"] == initial_score  # Hasn't changed yet
            assert r["pending_change"] is True

        # Nth call should trigger the change
        r_final = compute_traffic_light(spy_data, vix=45.0, db_path=tmp_db)
        assert r_final["score_changed"] is True

    def test_returns_all_keys(self, spy_data, tmp_db):
        result = compute_traffic_light(spy_data, vix=20.0, db_path=tmp_db)
        expected_keys = [
            "vix_signal", "vix_score", "vix_value",
            "trend_signal", "trend_score", "spy_close", "spy_sma200", "spy_pct_above_sma200",
            "credit_signal", "credit_score", "credit_spread", "credit_z_score",
            "raw_score", "total_score", "sizing_multiplier", "regime_label",
            "persistence_days", "score_changed", "pending_change",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"
```

---

## PARTS 2-7: [Continued with same level of detail]

Due to the massive scope, Parts 2-7 follow the same implementation-level pattern as Part 1. Each Part includes:

**For every new function:**
- Complete implementation (not just signature)
- Docstring with Args/Returns
- Error handling matching codebase pattern (try/except with logger.warning, never bare except)
- Type hints matching existing style (str | None, not Optional[str])

**For every database change:**
- Exact SQL (CREATE TABLE or ALTER TABLE)
- Safe migration pattern (try ALTER, except OperationalError: pass)
- Location in _ensure_all_tables() or journal/store.py

**For every integration point:**
- Exact file path and approximate line number
- The existing code pattern to match
- What imports to add
- What parameters to pass

**For every API endpoint:**
- Route decorator with path
- Function signature
- Import pattern
- Error handling pattern
- Corresponding frontend api.js export

**For every frontend component:**
- JSX component with Tailwind classes matching existing dashboard style
- React Query hook pattern matching existing pages
- Route registration in App.jsx
- Navigation entry in Layout.jsx

**For every test:**
- Complete test file following test_gate_evaluator.py pattern
- Fixtures with tmp_path and sqlite3
- Class-based test organization
- Boundary value tests for every threshold

---

## PART 2: AI Council Redesign — Vote-First Protocol

> **Read `src/council/agents.py`, `src/council/protocol.py`, and `src/council/engine.py` in full before implementing.**
> **Read `docs/research/AI_Council_Redesign__5-Agent_Strategic_Brain.md` in full.**

### 2A. Rewrite `src/council/agents.py`

Replace the current 5 agents. The existing code has `AGENT_PROMPTS` dict mapping agent names to system prompts, and `AGENT_DATA_FUNCTIONS` dict mapping agent names to data-gathering functions. Keep this architecture but replace the contents.

**New agent definitions:**

```python
AGENT_PROMPTS = {
    "tactical_operator": TACTICAL_OPERATOR_PROMPT,
    "strategic_architect": STRATEGIC_ARCHITECT_PROMPT,
    "red_team": RED_TEAM_PROMPT,
    "innovation_engine": INNOVATION_ENGINE_PROMPT,
    "macro_navigator": MACRO_NAVIGATOR_PROMPT,
}

AGENT_NAMES = list(AGENT_PROMPTS.keys())

AGENT_DATA_FUNCTIONS = {
    "tactical_operator": gather_tactical_data,
    "strategic_architect": gather_strategic_data,
    "red_team": gather_risk_data,
    "innovation_engine": gather_innovation_data,
    "macro_navigator": gather_macro_data,
}
```

**Each system prompt MUST:**
1. Define the analytical framework (not just a persona)
2. State the core question for this session type
3. List specific evaluation criteria
4. **Require structured JSON output** (not prose) with this exact schema:

```
OUTPUT FORMAT: Respond with ONLY a JSON object (no markdown, no preamble):
{
  "agent": "<your_agent_name>",
  "direction": "bullish" | "neutral" | "bearish",
  "confidence": <0.0 to 1.0>,
  "position_sizing_recommendation": <0.25 to 1.5>,
  "cash_reserve_recommendation_pct": <10 to 50>,
  "scan_aggressiveness": "conservative" | "normal" | "aggressive",
  "sector_tilts": {"prefer": ["sector1"], "avoid": ["sector2"]},
  "key_reasoning": "<one paragraph maximum>",
  "key_risk": "<one sentence>",
  "falsifiable_prediction": "<specific testable claim with date>"
}
```

**TACTICAL OPERATOR prompt** — core question: "What does current data tell us about the next 1-5 days?"
- Framework: market microstructure, regime detection, order flow analysis, volatility assessment
- Data: VIX + VIX term structure, ATR, credit spreads, overnight futures, current positions, recent scan results, Traffic Light score
- Evaluation criteria: Is the regime favorable for pullback entries? Is vol expanding or contracting? Are credit markets confirming or diverging?

**STRATEGIC ARCHITECT prompt** — core question: "How should we allocate capital and attention?"
- Framework: portfolio theory, Kelly criterion, phase gate evaluation, resource allocation
- Data: phase gate progress, capital levels, strategy performance, model health metrics, HSHS score, roadmap status
- Evaluation criteria: Are we on track for the 50-trade gate? Should we be more conservative or aggressive? Are we building the data asset fast enough?

**RED TEAM / RISK SENTINEL prompt** — core question: "What are we missing, and what kills us?"
- Framework: adversarial pre-mortem, tail risk analysis, competitive threat assessment
- Data: current drawdown, sector concentration, correlation between positions, model health, alpha decay indicators, recent losses
- Evaluation criteria: What's the worst-case 2σ event? Which positions are most vulnerable? What would make all our positions move against us simultaneously?

**INNOVATION ENGINE prompt** — core question: "What can we build that we couldn't before?"
- Framework: R&D pipeline assessment, ML experiment design, technical feasibility
- Data: training data quality trends, model version history, feature importance, research digest, template fallback rate
- Evaluation criteria: Is the training pipeline producing better data? Are there quick wins in the feature engine? Should we prioritize model improvement or data accumulation?

**MACRO NAVIGATOR prompt** — core question: "How is the world changing around us?"
- Framework: macro-financial analysis, regulatory monitoring, market structure evolution
- Data: FRED macro data (34+ series), regime history, sector rotation, credit conditions, Fed communication analysis, research digest
- Evaluation criteria: Where are we in the economic cycle? What regime transition risks exist? Any regulatory changes that affect our operations?

**Each `gather_*_data()` function MUST pull REAL data from SQLite.** Follow the existing pattern in agents.py (which already queries recommendations, shadow_trades, council_sessions, VIX data, etc.). Each function should return a formatted string that gets injected into the user prompt.

Example for `gather_tactical_data()`:
```python
def gather_tactical_data(db_path: str = DB_PATH) -> str:
    """Gather real-time tactical data for the Tactical Operator agent."""
    parts = []

    # VIX and term structure
    try:
        with sqlite3.connect(db_path) as conn:
            vix_row = conn.execute(
                "SELECT vix_close, vix9d, vix3m, vix1y FROM vix_term_structure "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if vix_row:
                parts.append(f"VIX: {vix_row[0]:.1f} | VIX9D: {vix_row[1]:.1f} | "
                           f"VIX3M: {vix_row[2]:.1f} | VIX1Y: {vix_row[3]:.1f}")
                contango = "contango" if vix_row[0] < vix_row[2] else "backwardation"
                parts.append(f"Term structure: {contango}")
    except Exception as e:
        logger.warning("[COUNCIL] Tactical VIX query failed: %s", e)

    # Traffic Light
    try:
        row = conn.execute(
            "SELECT current_score, current_multiplier FROM traffic_light_state WHERE id = 1"
        ).fetchone()
        if row:
            parts.append(f"Traffic Light: {row[0]}/6 (×{row[1]:.1f})")
    except Exception:
        pass

    # Recent scan results
    try:
        with sqlite3.connect(db_path) as conn:
            recent = conn.execute(
                "SELECT scan_time, packet_worthy, risk_passed, avg_conviction, "
                "traffic_light_score, traffic_light_multiplier "
                "FROM scan_metrics ORDER BY created_at DESC LIMIT 3"
            ).fetchall()
            if recent:
                parts.append("\nLast 3 scans:")
                for r in recent:
                    parts.append(f"  {r[0]}: {r[1]} packets, {r[2]} passed risk, "
                               f"avg conviction {r[3]:.1f}, TL={r[4]}/6")
    except Exception as e:
        logger.warning("[COUNCIL] Tactical scan query failed: %s", e)

    # Current open positions
    try:
        with sqlite3.connect(db_path) as conn:
            positions = conn.execute(
                "SELECT ticker, pnl_pct, "
                "julianday('now') - julianday(actual_entry_time) as days_held "
                "FROM shadow_trades WHERE status = 'open' "
                "ORDER BY pnl_pct DESC"
            ).fetchall()
            if positions:
                parts.append(f"\nOpen positions ({len(positions)}):")
                for p in positions:
                    emoji = "📈" if (p[1] or 0) > 0 else "📉"
                    parts.append(f"  {emoji} {p[0]}: {p[1]:+.1f}% ({p[2]:.0f}d)")
    except Exception as e:
        logger.warning("[COUNCIL] Tactical positions query failed: %s", e)

    return "\n".join(parts) if parts else "No tactical data available."
```

**Write similar real-data gathering functions for all 5 agents.** Each must query actual tables, handle missing data gracefully, and never crash.

### 2B. Rewrite `src/council/protocol.py` to vote-first

**Replace the 3-round always-runs protocol with conditional rounds.**

Key changes to the existing functions:

**`run_round_1()`** — keep the structure but update the system prompts to require JSON output. Parse each agent's response as JSON using `json.loads()`. If JSON parsing fails, use `_default_response()` with the parse error logged (not silently swallowed — this was audit issue M4).

**New: `aggregate_round_1()` function:**
```python
def aggregate_round_1(assessments: list[dict], session_type: str = "daily") -> dict:
    """Compute confidence-weighted aggregated vote from Round 1 assessments.

    Domain weights vary by session type (daily/weekly/monthly).
    """
    DOMAIN_WEIGHTS = {
        "daily": {
            "tactical_operator": 1.2,
            "strategic_architect": 0.8,
            "red_team": 1.0,
            "innovation_engine": 0.6,
            "macro_navigator": 0.9,
        },
        "weekly": {
            "tactical_operator": 0.8,
            "strategic_architect": 1.3,
            "red_team": 1.0,
            "innovation_engine": 1.0,
            "macro_navigator": 1.2,
        },
    }
    weights = DOMAIN_WEIGHTS.get(session_type, DOMAIN_WEIGHTS["daily"])

    direction_map = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}

    numerator = 0.0
    denominator = 0.0
    vote_distribution = {"bullish": 0, "neutral": 0, "bearish": 0}

    for a in assessments:
        agent = a.get("agent", "unknown")
        direction = a.get("direction", "neutral")
        confidence = max(0.0, min(1.0, a.get("confidence", 0.5)))
        domain_weight = weights.get(agent, 1.0)

        vote = direction_map.get(direction, 0.0)
        numerator += vote * confidence * domain_weight
        denominator += confidence * domain_weight
        vote_distribution[direction] = vote_distribution.get(direction, 0) + 1

    score = numerator / denominator if denominator > 0 else 0.0

    # Determine consensus
    max_votes = max(vote_distribution.values())
    consensus_count = sum(1 for v in vote_distribution.values() if v == max_votes)
    total_agents = len(assessments)
    consensus_type = f"{max_votes}-{total_agents - max_votes}"

    return {
        "aggregated_score": round(score, 3),
        "direction": "bullish" if score > 0.3 else "bearish" if score < -0.3 else "neutral",
        "vote_distribution": vote_distribution,
        "consensus_type": consensus_type,
        "consensus_reached": max_votes >= 3,  # 3/5 = consensus
        "round2_needed": max_votes < 3,
    }
```

**`run_round_2()`** — only called if `round2_needed` is True. Agents see Round 1 outputs and can update their positions. Track if any agent flips direction (sycophancy flag).

**Remove `run_round_3()` from daily sessions.** Keep available only for weekly/monthly.

**Update `tally_votes()`** to use the new aggregation logic.

### 2C-2G. [Continue with same implementation-level detail for:]
- Structured JSON session output stored in `council_sessions.result_json` (exact ALTER TABLE SQL, exact JSON schema)
- Parameter auto-application with rate limiters (exact implementation with ±25%/day, ±50%/week caps)
- Calibration tracking table (exact CREATE TABLE, auto-verification job in watch.py)
- Council dashboard update (React component with vote cards, dissent highlighting, calibration scorecard)
- Complete test suite for council

---

## PART 3: Implementation Shortfall Tracking

### 3A. Add columns to shadow_trades

**File:** `src/journal/store.py`

In the `initialize_database()` function, after the CREATE TABLE for shadow_trades, add safe ALTER statements:
```python
# Implementation Shortfall tracking (Research Agenda, Q5)
for col_sql in [
    "ALTER TABLE shadow_trades ADD COLUMN signal_price REAL",
    "ALTER TABLE shadow_trades ADD COLUMN implementation_shortfall_bps REAL",
]:
    try:
        conn.execute(col_sql)
    except sqlite3.OperationalError:
        pass  # Column already exists
```

Also add to `_ensure_all_tables()` in `watch.py` with the same safe ALTER pattern.

### 3B. Capture signal price in scan pipeline

**File:** `src/services/scan_service.py`

Inside the per-ticker loop, BEFORE the LLM call, after the ticker qualifies as packet-worthy:
```python
    # Capture signal price for Implementation Shortfall tracking
    signal_price = float(features[ticker].get("current_price", 0))
    features[ticker]["signal_price"] = signal_price
```

Then in `open_shadow_trade()`, read `features.get("signal_price")` and store it:
```python
    signal_price = features.get("signal_price")
    if signal_price:
        # Store alongside the trade
        conn.execute(
            "UPDATE shadow_trades SET signal_price = ? WHERE trade_id = ?",
            (signal_price, trade_id),
        )
```

### 3C. Compute IS on fill

**File:** `src/shadow_trading/executor.py`

After receiving the Alpaca fill price (in the bracket order submission section, where `fill_price` is extracted from the Alpaca response):
```python
    # Compute Implementation Shortfall
    signal_price = features.get("signal_price")
    if signal_price and fill_price and signal_price > 0:
        is_bps = ((float(fill_price) - signal_price) / signal_price) * 10000
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE shadow_trades SET implementation_shortfall_bps = ? WHERE trade_id = ?",
                    (round(is_bps, 2), trade_id),
                )
        except Exception as e:
            logger.warning("[IS] Failed to store IS for %s: %s", ticker, e)

        # Alert if rolling average exceeds threshold
        try:
            with sqlite3.connect(db_path) as conn:
                avg_is = conn.execute(
                    "SELECT AVG(implementation_shortfall_bps) FROM "
                    "(SELECT implementation_shortfall_bps FROM shadow_trades "
                    "WHERE implementation_shortfall_bps IS NOT NULL "
                    "ORDER BY created_at DESC LIMIT 20)"
                ).fetchone()
                if avg_is and avg_is[0] and avg_is[0] > 10:
                    from src.notifications.telegram import send_telegram, is_telegram_enabled
                    if is_telegram_enabled():
                        send_telegram(
                            f"⚠️ Implementation Shortfall Alert\n"
                            f"Rolling 20-trade avg: {avg_is[0]:.1f} bps (threshold: 10)\n"
                            f"Latest: {ticker} = {is_bps:.1f} bps\n"
                            f"Consider switching to limit-at-ask orders."
                        )
        except Exception as e:
            logger.warning("[IS] IS alert check failed: %s", e)
```

### 3D. Limit orders at the ask

**File:** `config/settings.example.yaml` — add:
```yaml
execution:
  order_type: "limit_at_ask"  # "market" or "limit_at_ask"
  limit_timeout_seconds: 300   # Cancel unfilled limits after 5 minutes
```

**File:** `src/shadow_trading/executor.py`

In the bracket order placement section, check the config:
```python
    order_type = config.get("execution", {}).get("order_type", "market")
    if order_type == "limit_at_ask":
        # Get current ask price
        try:
            from src.shadow_trading.alpaca_adapter import get_latest_quote
            quote = get_latest_quote(ticker)
            ask_price = quote.get("ask_price", entry_price)
            order_params["type"] = "limit"
            order_params["limit_price"] = ask_price
            order_params["time_in_force"] = "day"  # Cancel at EOD if not filled
            logger.info("[EXEC] Using limit-at-ask for %s at $%.2f", ticker, ask_price)
        except Exception as e:
            logger.warning("[EXEC] Failed to get ask for %s, falling back to market: %s", ticker, e)
            # Fall back to market order
```

### 3E. Tests — `tests/test_implementation_shortfall.py`

```python
"""Tests for Implementation Shortfall tracking."""

import sqlite3
import pytest


class TestISComputation:
    def test_positive_slippage(self):
        """Fill above signal = positive IS (bad for buys)."""
        signal = 100.0
        fill = 100.05
        is_bps = ((fill - signal) / signal) * 10000
        assert is_bps == pytest.approx(5.0, abs=0.1)

    def test_negative_slippage(self):
        """Fill below signal = negative IS (good for buys = price improvement)."""
        signal = 100.0
        fill = 99.98
        is_bps = ((fill - signal) / signal) * 10000
        assert is_bps == pytest.approx(-2.0, abs=0.1)

    def test_zero_slippage(self):
        signal = 100.0
        fill = 100.0
        is_bps = ((fill - signal) / signal) * 10000
        assert is_bps == pytest.approx(0.0, abs=0.01)
```

---

## PART 4: PEAD Enrichment Features for Pullback Adapter

> **Read `docs/research/PEAD_for_SP100__The_Drift_Evolved.md` in full.**
> **Read `src/data_enrichment/enricher.py` and `src/llm/packet_writer.py` to understand integration points.**

### 4A. Create `src/data_enrichment/earnings_signals.py`

```python
"""Earnings-adjacent signal computation for pullback enrichment.

NOT a separate strategy — these are features added to the pullback adapter's
input prompt to improve trade quality near earnings events.

Research: PEAD_for_SP100__The_Drift_Evolved.md
- Earnings surprise magnitude: Finnhub company_earnings()
- Revenue-EPS concordance: concordant beats/misses produce stronger signals
- Analyst revision velocity: fast upward revisions + beat = strongest signal
- Recommendation inconsistency: McCarthy (2025): 2.5-4.5× stronger drift when
  surprise direction is inconsistent with prior analyst consensus rating
- Earnings proximity: days to next announcement (already in earnings.py)
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DB_PATH = "ai_research_desk.sqlite3"


def compute_earnings_signals(
    ticker: str,
    db_path: str = DB_PATH,
) -> dict:
    """Compute earnings-adjacent signals for a ticker.

    Returns:
        {
            "earnings_proximity_days": int|None,
            "last_surprise_pct": float|None,
            "last_surprise_direction": "beat"|"miss"|"inline"|None,
            "last_revenue_eps_concordant": bool|None,
            "analyst_revision_velocity_30d": float|None,
            "recommendation_inconsistency": bool|None,
            "earnings_signal_strength": "strong"|"moderate"|"weak"|"none",
            "include_in_prompt": bool,
        }
    """
    result = {
        "earnings_proximity_days": None,
        "last_surprise_pct": None,
        "last_surprise_direction": None,
        "last_revenue_eps_concordant": None,
        "analyst_revision_velocity_30d": None,
        "recommendation_inconsistency": None,
        "earnings_signal_strength": "none",
        "include_in_prompt": False,
    }

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # ── 1. Earnings proximity ─────────────────────────────
            now = datetime.now(ET)
            today_str = now.strftime("%Y-%m-%d")

            next_earnings = conn.execute(
                "SELECT report_date FROM earnings_calendar "
                "WHERE ticker = ? AND report_date >= ? "
                "ORDER BY report_date ASC LIMIT 1",
                (ticker, today_str),
            ).fetchone()

            if next_earnings:
                next_date = datetime.strptime(next_earnings["report_date"], "%Y-%m-%d")
                result["earnings_proximity_days"] = (next_date - now).days

            # ── 2. Last earnings surprise ─────────────────────────
            # Finnhub stores actual vs estimate in earnings_calendar or a dedicated table
            last_earnings = conn.execute(
                "SELECT actual, estimate, report_date, revenue_actual, revenue_estimate "
                "FROM earnings_calendar "
                "WHERE ticker = ? AND report_date < ? AND actual IS NOT NULL "
                "ORDER BY report_date DESC LIMIT 1",
                (ticker, today_str),
            ).fetchone()

            if last_earnings and last_earnings["estimate"]:
                actual = last_earnings["actual"]
                estimate = last_earnings["estimate"]
                surprise = actual - estimate
                surprise_pct = (surprise / abs(estimate)) * 100 if estimate != 0 else 0

                result["last_surprise_pct"] = round(surprise_pct, 2)
                if surprise_pct > 2:
                    result["last_surprise_direction"] = "beat"
                elif surprise_pct < -2:
                    result["last_surprise_direction"] = "miss"
                else:
                    result["last_surprise_direction"] = "inline"

                # Revenue-EPS concordance
                rev_actual = last_earnings.get("revenue_actual")
                rev_est = last_earnings.get("revenue_estimate")
                if rev_actual and rev_est and rev_est > 0:
                    rev_beat = rev_actual > rev_est
                    eps_beat = actual > estimate
                    result["last_revenue_eps_concordant"] = rev_beat == eps_beat

            # ── 3. Analyst revision velocity ──────────────────────
            thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
            revisions = conn.execute(
                "SELECT target_mean, created_at FROM analyst_estimates "
                "WHERE ticker = ? AND created_at >= ? "
                "ORDER BY created_at ASC",
                (ticker, thirty_days_ago),
            ).fetchall()

            if len(revisions) >= 2:
                first = revisions[0]["target_mean"]
                last = revisions[-1]["target_mean"]
                if first and last and first > 0:
                    velocity = ((last - first) / first) * 100  # % change over 30 days
                    result["analyst_revision_velocity_30d"] = round(velocity, 2)

            # ── 4. Recommendation inconsistency (McCarthy 2025) ──
            consensus = conn.execute(
                "SELECT buy, hold, sell, strong_buy, strong_sell "
                "FROM analyst_estimates "
                "WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()

            if consensus and result["last_surprise_direction"]:
                total_analysts = sum(
                    (consensus[k] or 0) for k in ["buy", "hold", "sell", "strong_buy", "strong_sell"]
                )
                if total_analysts > 0:
                    buy_pct = ((consensus["buy"] or 0) + (consensus["strong_buy"] or 0)) / total_analysts
                    sell_pct = ((consensus["sell"] or 0) + (consensus["strong_sell"] or 0)) / total_analysts

                    # Inconsistency: beat + sell-rated, or miss + buy-rated
                    if result["last_surprise_direction"] == "beat" and sell_pct > 0.3:
                        result["recommendation_inconsistency"] = True
                    elif result["last_surprise_direction"] == "miss" and buy_pct > 0.6:
                        result["recommendation_inconsistency"] = True
                    else:
                        result["recommendation_inconsistency"] = False

            # ── 5. Composite signal strength ──────────────────────
            strength_score = 0
            if result["last_surprise_direction"] in ("beat", "miss"):
                strength_score += 1
            if result["last_revenue_eps_concordant"]:
                strength_score += 1
            if result["recommendation_inconsistency"]:
                strength_score += 2  # 2.5-4.5× stronger per McCarthy 2025
            if result["analyst_revision_velocity_30d"] and abs(result["analyst_revision_velocity_30d"]) > 3:
                strength_score += 1

            if strength_score >= 3:
                result["earnings_signal_strength"] = "strong"
            elif strength_score >= 1:
                result["earnings_signal_strength"] = "moderate"
            else:
                result["earnings_signal_strength"] = "weak"

            # Include in prompt if earnings within 30 days OR last earnings within 10 days
            proximity = result.get("earnings_proximity_days")
            if proximity is not None and proximity <= 30:
                result["include_in_prompt"] = True
            elif last_earnings:
                last_date = datetime.strptime(last_earnings["report_date"], "%Y-%m-%d")
                days_since = (now - last_date.replace(tzinfo=ET)).days
                if days_since <= 10:
                    result["include_in_prompt"] = True

    except Exception as e:
        logger.warning("[EARNINGS] Signal computation failed for %s: %s", ticker, e)

    return result
```

### 4B. Wire into enrichment pipeline

**File:** `src/data_enrichment/enricher.py`

After the existing enrichment modules (fundamentals, insiders, news, macro), add:
```python
    # ── Earnings signals (PEAD enrichment for pullback adapter) ──
    try:
        from src.data_enrichment.earnings_signals import compute_earnings_signals
        for ticker in features:
            earnings = compute_earnings_signals(ticker, db_path=db_path)
            features[ticker]["earnings_signals"] = earnings
    except Exception as e:
        logger.warning("[ENRICHMENT] Earnings signals failed: %s", e)
```

### 4C. Add to LLM prompt template

**File:** `src/llm/packet_writer.py`

In `_build_feature_prompt()`, after the existing MACRO CONTEXT section (~line where `macro_text` is appended), add conditionally:

```python
    # SECTION 8: Earnings Context (PEAD enrichment — only when earnings-adjacent)
    earnings = features.get("earnings_signals", {})
    if earnings.get("include_in_prompt", False):
        proximity = earnings.get("earnings_proximity_days")
        surprise = earnings.get("last_surprise_pct")
        direction = earnings.get("last_surprise_direction", "unknown")
        concordant = earnings.get("last_revenue_eps_concordant")
        revision_vel = earnings.get("analyst_revision_velocity_30d")
        inconsistent = earnings.get("recommendation_inconsistency")
        strength = earnings.get("earnings_signal_strength", "none")

        earnings_lines = [f"\n=== EARNINGS CONTEXT ==="]
        if proximity is not None:
            earnings_lines.append(f"Days to next earnings: {proximity}")
        if surprise is not None:
            earnings_lines.append(f"Last earnings surprise: {surprise:+.1f}% ({direction})")
        if concordant is not None:
            earnings_lines.append(f"Revenue-EPS concordance: {'concordant' if concordant else 'mixed'}")
        if revision_vel is not None:
            direction_word = "rising" if revision_vel > 0 else "falling" if revision_vel < 0 else "stable"
            earnings_lines.append(f"Analyst revision trend (30d): {direction_word} ({revision_vel:+.1f}%)")
        if inconsistent is not None:
            earnings_lines.append(f"Recommendation vs surprise: {'inconsistent (2.5-4.5x stronger signal)' if inconsistent else 'consistent'}")
        earnings_lines.append(f"Earnings signal strength: {strength}")

        prompt += "\n".join(earnings_lines)
```

### 4D. Tests — `tests/test_earnings_signals.py`

```python
"""Tests for src.data_enrichment.earnings_signals."""

import sqlite3
import pytest
from datetime import datetime, timedelta

from src.data_enrichment.earnings_signals import compute_earnings_signals


@pytest.fixture
def earnings_db(tmp_path):
    """DB with earnings_calendar and analyst_estimates tables."""
    db = str(tmp_path / "test.sqlite3")
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE earnings_calendar (
            id INTEGER PRIMARY KEY, ticker TEXT, report_date TEXT,
            actual REAL, estimate REAL, revenue_actual REAL, revenue_estimate REAL)""")
        conn.execute("""CREATE TABLE analyst_estimates (
            id INTEGER PRIMARY KEY, ticker TEXT, target_mean REAL,
            buy INTEGER, hold INTEGER, sell INTEGER, strong_buy INTEGER, strong_sell INTEGER,
            created_at TEXT)""")
    return db


class TestEarningsSignals:
    def test_no_data_returns_defaults(self, earnings_db):
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        assert result["earnings_signal_strength"] == "none"
        assert result["include_in_prompt"] is False

    def test_beat_detected(self, earnings_db):
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        with sqlite3.connect(earnings_db) as conn:
            conn.execute(
                "INSERT INTO earnings_calendar (ticker, report_date, actual, estimate) VALUES (?, ?, ?, ?)",
                ("AAPL", yesterday, 1.50, 1.30),
            )
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        assert result["last_surprise_direction"] == "beat"
        assert result["last_surprise_pct"] > 0
        assert result["include_in_prompt"] is True  # within 10 days

    def test_concordance_both_beat(self, earnings_db):
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        with sqlite3.connect(earnings_db) as conn:
            conn.execute(
                "INSERT INTO earnings_calendar (ticker, report_date, actual, estimate, revenue_actual, revenue_estimate) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", yesterday, 1.50, 1.30, 100.0, 95.0),
            )
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        assert result["last_revenue_eps_concordant"] is True

    def test_proximity_trigger(self, earnings_db):
        future = (datetime.utcnow() + timedelta(days=15)).strftime("%Y-%m-%d")
        with sqlite3.connect(earnings_db) as conn:
            conn.execute(
                "INSERT INTO earnings_calendar (ticker, report_date) VALUES (?, ?)",
                ("AAPL", future),
            )
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        assert result["earnings_proximity_days"] == pytest.approx(15, abs=1)
        assert result["include_in_prompt"] is True

    def test_no_prompt_when_distant(self, earnings_db):
        future = (datetime.utcnow() + timedelta(days=60)).strftime("%Y-%m-%d")
        with sqlite3.connect(earnings_db) as conn:
            conn.execute(
                "INSERT INTO earnings_calendar (ticker, report_date) VALUES (?, ?)",
                ("AAPL", future),
            )
        result = compute_earnings_signals("AAPL", db_path=earnings_db)
        assert result["include_in_prompt"] is False
```

---

## PARTS 5-7: Validation Dashboard, HSHS Page, Documentation

### Part 5: Verify/complete the Validation page CC built

CC already created `frontend/src/pages/Validation.jsx` and the system validator backend. **Verify:**
1. The page is registered in `App.jsx` routes (add `<Route path="/validation" element={<Validation />} />`)
2. The page is in `Layout.jsx` navigation
3. The API endpoint exists in `src/api/routes/system.py`
4. The endpoint is also in `cloud_app.py` for Render dashboard
5. The `validation_results` table exists in `_ensure_all_tables()`
6. The daily 4:30 PM auto-run is in `watch.py`
7. Telegram notification fires on failures

**If any of these are missing, implement them following the existing patterns.**

### Part 6: HSHS Dashboard

Add HSHS visualization to the existing Health page (`frontend/src/pages/Health.jsx`):
- Fetch from `/api/health/hshs`
- Display 5-dimension radar chart using Recharts' `RadarChart` component
- Show composite score prominently
- Show phase-dependent weights (currently "early" phase)

### Part 7: Documentation — MANDATORY

**This is not optional. Every item must be completed.**

Run the verification commands at the very end:
```bash
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "LOC:" && find src -name "*.py" ! -path "*__pycache__*" -exec wc -l {} + | tail -1
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
echo "DB tables:" && grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | sed 's/.*CREATE TABLE IF NOT EXISTS //;s/ (.*//' | sort -u | wc -l
echo "API routes:" && grep -c "@app\.\|@router\." src/api/cloud_app.py src/api/routes/*.py 2>/dev/null
echo "CLI commands:" && grep -c "add_parser" src/main.py
echo "Notifications:" && grep -c "^def notify_" src/notifications/telegram.py
echo "Research docs:" && ls docs/research/*.md | wc -l
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
```

Update AGENTS.md with the EXACT numbers produced by these commands.

Update CHANGELOG.md with this sprint's changes.

Update docs/architecture.md with all new modules, tables, endpoints, and integration points.

Update docs/roadmap.md and docs/roadmap-complete.md with confirmed strategy decisions:
- Strategy #2 = Mean Reversion (Phase 2)
- Strategy #3 = Evolved PEAD (Phase 3)
- RL = Dr. GRPO, skip DPO
- PEAD enrichment features added to Phase 2
- Traffic Light built (Phase 1)

Add all 6 new research documents to `src/api/routes/docs.py` and `src/data_collection/docs_collector.py`.
